"""Idempotent file storage handling raw JSON, clean CSV, clean Parquet, and dataset manifests."""

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pyarrow as pa
import pyarrow.parquet as pq

from kairos.config.settings import get_settings
from kairos.schemas.common import DatasetManifest
from kairos.utils.logging_config import get_logger
from kairos.utils.security import resolve_safe_path

logger = get_logger("kairos.storage.file_store")


def compute_sha256(filepath: Union[str, Path]) -> str:
    """Computes SHA-256 hash of a file for integrity verification."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class FileStore:
    """Manages file persistence across raw, processed, manifests, and reports."""

    def __init__(self, base_dir: Optional[Path] = None):
        settings = get_settings()
        self.base_dir = Path(base_dir or settings.data_dir).resolve()
        self.raw_dir = self.base_dir / "raw"
        self.processed_dir = self.base_dir / "processed"
        self.manifests_dir = self.base_dir / "manifests"
        self.reports_dir = self.base_dir / "reports"

        # Ensure directory structure
        for d in [self.raw_dir, self.processed_dir, self.manifests_dir, self.reports_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def save_raw(self, domain: str, filename: str, payload: Union[Dict[str, Any], List[Any], str]) -> Path:
        """
        Saves raw payload deterministically to data/raw/{domain}/{filename}.
        Protects against path traversal.
        """
        domain_dir = self.raw_dir / domain
        domain_dir.mkdir(parents=True, exist_ok=True)
        safe_path = resolve_safe_path(domain_dir, filename)

        if isinstance(payload, (dict, list)):
            with open(safe_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
        else:
            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(str(payload))

        logger.info(f"Saved raw {domain} payload to {safe_path.relative_to(self.base_dir.parent)}")
        return safe_path

    def export_csv(
        self,
        domain: str,
        filename: str,
        records: List[Dict[str, Any]],
        fieldnames: Optional[List[str]] = None,
    ) -> Path:
        """Exports a list of dictionary records to a clean CSV file."""
        domain_dir = self.processed_dir / domain
        domain_dir.mkdir(parents=True, exist_ok=True)
        safe_path = resolve_safe_path(domain_dir, filename)

        if not records:
            # Create empty file with headers if fieldnames provided
            with open(safe_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if fieldnames:
                    writer.writerow(fieldnames)
            return safe_path

        keys = fieldnames or list(records[0].keys())
        with open(safe_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            for r in records:
                writer.writerow(r)

        logger.info(f"Exported {len(records)} records to CSV at {safe_path.relative_to(self.base_dir.parent)}")
        return safe_path

    def export_parquet(self, domain: str, filename: str, records: List[Dict[str, Any]]) -> Path:
        """Exports a list of dictionary records to a typed Parquet file via PyArrow."""
        domain_dir = self.processed_dir / domain
        domain_dir.mkdir(parents=True, exist_ok=True)
        safe_path = resolve_safe_path(domain_dir, filename)

        if not records:
            # Create an empty table
            table = pa.Table.from_pydict({})
            pq.write_table(table, safe_path)
            return safe_path

        # Convert dictionary records into column-oriented dict for PyArrow
        column_names = list(records[0].keys())
        col_data: Dict[str, List[Any]] = {k: [] for k in column_names}
        for r in records:
            for k in column_names:
                v = r.get(k)
                if isinstance(v, (dict, list)):
                    v = json.dumps(v, default=str)
                col_data[k].append(v)

        arrow_table = pa.Table.from_pydict(col_data)
        pq.write_table(arrow_table, safe_path, compression="snappy")

        logger.info(f"Exported {len(records)} records to Parquet at {safe_path.relative_to(self.base_dir.parent)}")
        return safe_path

    def export_jsonl(self, domain: str, filename: str, records: List[Dict[str, Any]]) -> Path:
        """Exports a list of dictionary records to a newline-delimited JSON (JSONL) file."""
        domain_dir = self.processed_dir / domain
        domain_dir.mkdir(parents=True, exist_ok=True)
        safe_path = resolve_safe_path(domain_dir, filename)

        with open(safe_path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, default=str) + "\n")

        logger.info(f"Exported {len(records)} records to JSONL at {safe_path.relative_to(self.base_dir.parent)}")
        return safe_path

    def save_manifest(self, manifest: DatasetManifest) -> Path:
        """Persists a dataset manifest to data/manifests/{manifest_id}.json."""
        manifest_filename = f"{manifest.manifest_id}.json"
        safe_path = resolve_safe_path(self.manifests_dir, manifest_filename)

        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(manifest.model_dump_json(indent=2))

        logger.info(f"Persisted dataset manifest: {safe_path.name}")
        return safe_path

