"""Official MCP servers over streamable HTTP (JSON-RPC): MoSPI eSankhyiki and NSE."""
from __future__ import annotations

import json
import os
from datetime import timedelta

from ._http import SourceError, base_symbol, iso, parse_date, request

MOSPI_URL = "https://mcp.mospi.gov.in/"        # verified keyless, 17 Nov 2026
NSE_URL = "https://mcp.nseindia.in/cmmkt/mcp"  # verified keyless, 17 Nov 2026
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


class McpClient:
    def __init__(self, url: str):
        self.url, self.headers, self._id = url, {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}, 0
        r = self._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "kairos", "version": "0.1"}})
        if r.headers.get("Mcp-Session-Id"):
            self.headers["Mcp-Session-Id"] = r.headers["Mcp-Session-Id"]
        request("POST", url, headers=self.headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=8)

    def _rpc(self, method, params):
        self._id += 1
        return request("POST", self.url, headers=self.headers, timeout=8,
                       json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})

    def call(self, tool: str, args: dict) -> dict:
        """tools/call -> parsed JSON of the first text content block."""
        r = self._rpc("tools/call", {"name": tool, "arguments": args})
        body = r.text.split("data:", 1)[1] if r.text.lstrip().startswith("event:") else r.text
        msg = json.loads(body)
        if "error" in msg or msg.get("result", {}).get("isError"):
            raise SourceError(f"MCP {tool} error: {str(msg.get('error') or msg['result'])[:120]}")
        try:
            data = json.loads(msg["result"]["content"][0]["text"])
        except (KeyError, IndexError, ValueError) as e:
            raise SourceError(f"MCP {tool}: unexpected response shape") from e
        if isinstance(data, dict) and data.get("error"):
            raise SourceError(f"MCP {tool}: {str(data['error'])[:120]}")
        return data


def mospi_mcp(symbol, company_name, now):
    url = os.getenv("KAIROS_MOSPI_MCP_URL", MOSPI_URL)
    c = McpClient(url)
    fy_start = now.year if now.month >= 4 else now.year - 1
    items, errs = [], []

    def cpi():
        for yr in (now.year, now.year - 1):
            rows = c.call("get_data", {"dataset": "CPI", "filters": {"base_year": "2024", "series": "Current", "year": str(yr),
                          "state_code": "1", "sector_code": "3", "division_code": "0", "limit": "12"}}).get("data") or []
            if rows:
                r = max(rows, key=lambda x: (int(x["year"]), _MONTHS.index(x["month"])))
                period = f"{r['month']} {r['year']}"
                return {"title": f"India CPI (combined, all-India) inflation, {period}: {r['inflation']}% y/y",
                        "summary": f"CPI general index {r['index']} (base 2024=100), year-on-year inflation {r['inflation']}%.",
                        "value": float(r["inflation"]), "unit": "% y/y", "period": period, "indicator": "CPI inflation", "as_of": iso(parse_date(f"1 {period}"))}

    def iip():
        for fy in (f"{fy_start}-{str(fy_start + 1)[2:]}", f"{fy_start - 1}-{str(fy_start)[2:]}"):
            rows = c.call("get_data", {"dataset": "IIP", "filters": {"frequency": "Monthly", "type": "General", "base_year": "2022-23",
                          "financial_year": fy, "limit": "12"}}).get("data") or []
            if rows:
                r = max(rows, key=lambda x: (int(x["year"]), _MONTHS.index(x["month"])))
                period = f"{r['month']} {r['year']}"
                return {"title": f"India IIP (general) growth, {period}: {r['growth_rate']}% y/y",
                        "summary": f"Index of Industrial Production general index {r['index']} (base 2022-23=100), growth {r['growth_rate']}% y/y.",
                        "value": float(r["growth_rate"]), "unit": "% y/y", "period": period, "indicator": "IIP growth", "as_of": iso(parse_date(f"1 {period}"))}

    def gdp():  # YoY on constant-price GDP, computed here from two NAS releases
        def quarters(fy):
            rows = c.call("get_data", {"dataset": "NAS", "filters": {"base_year": "2022-23", "series": "Current", "frequency_code": "Quarterly",
                          "indicator_code": "5", "year": fy}}).get("data") or []
            return {r["quarter"]: float(r["constant_price"]) for r in rows}
        for y in (fy_start, fy_start - 1):
            cur, prev = quarters(f"{y}-{str(y + 1)[2:]}"), quarters(f"{y - 1}-{str(y)[2:]}")
            q = max((k for k in cur if k in prev), default=None)
            if q:
                g = round((cur[q] / prev[q] - 1) * 100, 2)
                return {"title": f"India real GDP growth, {q} FY{y}-{str(y + 1)[2:]}: {g}% y/y (computed)",
                        "summary": f"Constant-price GDP (base 2022-23) INR crore {cur[q]:,.0f} vs {prev[q]:,.0f} a year earlier; growth computed by KAIROS from two MoSPI NAS values.",
                        "value": g, "unit": "% y/y", "period": f"{q} FY{y}-{str(y + 1)[2:]}", "indicator": "GDP growth (computed)"}

    for fn in (cpi, iip, gdp):
        try:
            it = fn()
            if it:
                items.append({**it, "url": "https://esankhyiki.mospi.gov.in/", "relevance": "MARKET_CONTEXT"})
        except (SourceError, ValueError, KeyError, TypeError) as e:
            errs.append(f"{fn.__name__}: {e}")
    if not items and errs:
        raise SourceError("; ".join(errs))
    dates = [i.pop("as_of") for i in items if i.get("as_of")]
    for i in items:
        i["published_at"] = None  # statistical period, not a publication date
    return {"status": "ok" if items else "empty", "items": items, "as_of": max(dates) if dates else None, "url": url,
            "reason": ("partial: " + "; ".join(errs)) if errs else (None if items else "no data returned")}


def nse_mcp(symbol, company_name, now):
    url = os.getenv("KAIROS_NSE_MCP_URL", NSE_URL)
    sym = base_symbol(symbol)
    c = McpClient(url)
    items, errs = [], []
    try:
        s = c.call("cm_get_stock_quote", {"symbol": sym})["stock"]
        ts = parse_date(s.get("latestTimestamp"))
        items.append({"title": f"{sym} last traded price INR {s['lastTradedPrice']} ({s['perChange']:+}%)",
                      "url": f"https://www.nseindia.com/get-quotes/equity?symbol={sym}", "published_at": iso(ts),
                      "summary": (f"Series {s.get('series')}; open {s.get('openPrice')}, high {s.get('highPrice')}, low {s.get('lowPrice')}, "
                                  f"prev close {s.get('preClosePrice')}; volume {s.get('volume')}; 52w range {s.get('fiftyTwoWeekLow')}-{s.get('fiftyTwoWeekHigh')}."),
                      "relevance": "TICKER_SPECIFIC", "value": s["lastTradedPrice"], "unit": "INR",
                      "period": s.get("latestTimestamp"), "indicator": "last traded price"})
    except (SourceError, KeyError, TypeError) as e:
        errs.append(f"quote: {e}")
    try:
        ix = c.call("cm_get_index_quote", {"indexName": "NIFTY 50"})["index"]
        ts = parse_date(ix.get("timeVal"))
        items.append({"title": f"NIFTY 50 {ix['last']} ({ix['percChange']:+}%)", "url": "https://www.nseindia.com/market-data/live-market-indices",
                      "published_at": iso(ts), "summary": f"Open {ix.get('open')}, high {ix.get('high')}, low {ix.get('low')}, prev close {ix.get('previousClose')}.",
                      "relevance": "MARKET_CONTEXT", "value": ix["last"], "unit": "index points", "period": ix.get("timeVal"), "indicator": "NIFTY 50"})
    except (SourceError, KeyError, TypeError) as e:
        errs.append(f"index: {e}")
    if not items and errs:
        raise SourceError("; ".join(errs))
    dates = [i["published_at"] for i in items if i["published_at"]]
    return {"status": "ok", "items": items, "as_of": max(dates) if dates else None, "url": url,
            "reason": ("partial: " + "; ".join(errs)) if errs else None}
