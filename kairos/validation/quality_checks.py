"""Data quality validation, anomaly detection, quarantined error logging, and reporting."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from kairos.config.settings import get_settings
from kairos.utils.logging_config import get_logger
from kairos.utils.security import resolve_safe_path

logger = get_logger("kairos.validation.quality_checks")


class QuarantinedRecord(BaseModel):
    """Encapsulates a rejected record alongside reason and origin."""

    record_index: int
    raw_record: Dict[str, Any]
    validation_error: str
    quarantined_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class DataQualityReport(BaseModel):
    """Comprehensive data quality scorecard for an ingested Indian equities dataset."""

    report_id: str
    run_id: str
    domain: str
    source_provider: str
    data_classification: str
    total_records: int
    valid_records: int
    invalid_records: int
    duplicate_records: int
    missing_value_percentages: Dict[str, float]
    symbols: List[str]
    date_coverage_start: Optional[str] = None
    date_coverage_end: Optional[str] = None
    coverage_years: Optional[float] = None
    is_ten_year_complete: bool = False
    quote_delay_classification: Optional[str] = None
    api_warnings: List[str] = Field(default_factory=list)
    quarantine_file: Optional[str] = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class DataQualityChecker:
    """Validates datasets against deterministic business rules, tracking quarantined rows."""

    def __init__(self, reports_dir: Optional[Path] = None):
        settings = get_settings()
        self.reports_dir = Path(reports_dir or settings.reports_dir).resolve()
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def analyze_dataset(
        self,
        domain: str,
        records: List[Dict[str, Any]],
        required_fields: List[str],
        provider: str,
        data_classification: str,
        run_id: Optional[str] = None,
        date_field: Optional[str] = "date",
        symbol_field: Optional[str] = "symbol",
        quote_delay_classification: Optional[str] = None,
    ) -> Tuple[DataQualityReport, List[QuarantinedRecord]]:
        """
        Runs quality audits on a list of raw or clean records.
        Detects missing fields, nulls, duplicates, invalid OHLC, and assesses ~10-year coverage.
        """
        run_id = run_id or get_settings().run_id
        report_id = f"quality_report_{domain}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        total = len(records)
        quarantined: List[QuarantinedRecord] = []
        valid_records: List[Dict[str, Any]] = []

        field_null_counts: Dict[str, int] = {f: 0 for f in required_fields}
        symbols_found = set()
        dates_found = []
        seen_keys = set()
        duplicate_count = 0

        for idx, row in enumerate(records):
            errors = []

            # 1. Required field checks
            for rf in required_fields:
                val = row.get(rf)
                if val is None or (isinstance(val, str) and not val.strip()):
                    field_null_counts[rf] += 1
                    errors.append(f"Missing required field: '{rf}'")

            # 2. Duplicate detection
            sym = str(row.get(symbol_field or "symbol", "")).upper()
            dt = str(row.get(date_field or "date", ""))
            if sym and dt:
                key = f"{sym}_{dt}"
                if key in seen_keys:
                    duplicate_count += 1
                    errors.append(f"Duplicate symbol/date record: {key}")
                seen_keys.add(key)

            # 3. OHLC invariant checks for market data
            if domain == "market":
                o = row.get("open")
                h = row.get("high")
                l = row.get("low")
                c = row.get("close")
                if None not in (o, h, l, c):
                    try:
                        fo, fh, fl, fc = float(o), float(h), float(l), float(c)
                        if fh < fl:
                            errors.append(f"High ({fh}) < Low ({fl})")
                        if fh < max(fo, fc) or fl > min(fo, fc):
                            errors.append(f"High/Low does not envelope Open/Close (O:{fo}, H:{fh}, L:{fl}, C:{fc})")
                    except (ValueError, TypeError):
                        errors.append("Non-numeric OHLC values")

            if sym:
                symbols_found.add(sym)

            if dt:
                dates_found.append(dt)

            if errors:
                quarantined.append(
                    QuarantinedRecord(
                        record_index=idx,
                        raw_record=row,
                        validation_error="; ".join(errors),
                    )
                )
            else:
                valid_records.append(row)

        # Missing percentages
        missing_pcts = {
            f: round((count / total * 100.0), 2) if total > 0 else 0.0
            for f, count in field_null_counts.items()
        }

        # Date coverage and 10-year check
        dates_found.sort()
        start_date = dates_found[0] if dates_found else None
        end_date = dates_found[-1] if dates_found else None

        coverage_years = 0.0
        is_ten_year_complete = False
        if start_date and end_date and len(start_date) >= 10 and len(end_date) >= 10:
            try:
                d1 = datetime.strptime(start_date[:10], "%Y-%m-%d")
                d2 = datetime.strptime(end_date[:10], "%Y-%m-%d")
                coverage_years = round((d2 - d1).days / 365.25, 2)
                is_ten_year_complete = coverage_years >= 9.0
            except Exception:
                pass

        # Quarantine file persistence if any invalid rows detected
        quarantine_path = None
        if quarantined:
            q_filename = f"{report_id}_quarantined.json"
            q_full_path = resolve_safe_path(self.reports_dir, q_filename)
            with open(q_full_path, "w", encoding="utf-8") as f:
                json.dump([q.model_dump() for q in quarantined], f, indent=2)
            quarantine_path = str(q_full_path)
            logger.warning(f"Quarantined {len(quarantined)} invalid records to {q_full_path.name}")

        report = DataQualityReport(
            report_id=report_id,
            run_id=run_id,
            domain=domain,
            source_provider=provider,
            data_classification=data_classification,
            total_records=total,
            valid_records=len(valid_records),
            invalid_records=len(quarantined),
            duplicate_records=duplicate_count,
            missing_value_percentages=missing_pcts,
            symbols=sorted(list(symbols_found)),
            date_coverage_start=start_date,
            date_coverage_end=end_date,
            coverage_years=coverage_years if domain == "market" else None,
            is_ten_year_complete=is_ten_year_complete if domain == "market" else True,
            quote_delay_classification=quote_delay_classification,
            quarantine_file=quarantine_path,
        )

        self._save_report(report)
        return report, quarantined

    def _save_report(self, report: DataQualityReport) -> None:
        """Saves JSON and Markdown versions of the quality report."""
        # JSON
        json_path = resolve_safe_path(self.reports_dir, f"{report.report_id}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(report.model_dump_json(indent=2))

        # Markdown
        md_path = resolve_safe_path(self.reports_dir, f"{report.report_id}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# Data Quality Report: {report.domain.upper()} (Indian Equities)\n\n")
            f.write(f"- **Report ID**: `{report.report_id}`\n")
            f.write(f"- **Run ID**: `{report.run_id}`\n")
            f.write(f"- **Source Provider**: `{report.source_provider}`\n")
            f.write(f"- **Data Classification**: `{report.data_classification}`\n")
            f.write(f"- **Total Records**: {report.total_records}\n")
            f.write(f"- **Valid Records**: {report.valid_records}\n")
            f.write(f"- **Invalid / Quarantined**: {report.invalid_records}\n")
            f.write(f"- **Duplicates**: {report.duplicate_records}\n")
            if report.date_coverage_start and report.date_coverage_end:
                f.write(f"- **Date Coverage**: {report.date_coverage_start} to {report.date_coverage_end}\n")
            if report.coverage_years is not None:
                f.write(f"- **Historical Depth**: {report.coverage_years} years (10-Year Complete: {report.is_ten_year_complete})\n")
            if report.quote_delay_classification:
                f.write(f"- **Quote Delay Classification**: `{report.quote_delay_classification}`\n")
            f.write(f"- **Symbols**: {', '.join(report.symbols) if report.symbols else 'None'}\n\n")

            f.write("### Missing Value Percentages\n")
            for field, pct in report.missing_value_percentages.items():
                f.write(f"- `{field}`: {pct}%\n")
            if report.quarantine_file:
                f.write(f"\n> [!WARNING] Quarantined records logged in `{Path(report.quarantine_file).name}`\n")

        logger.info(f"Generated quality report: {report.report_id}")
