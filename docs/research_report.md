# Downloadable research report

`GET /api/runs/{run_id}/report` returns one self-contained HTML document (inline CSS and SVG, no external assets) built by `kairos/web/report.py` from data already stored for the run: the result JSON, run events and the evidence directory (`runtime/evidence/<run_id>`). Nothing is re-fetched.

- Default: `Content-Disposition: attachment; filename="KAIROS_<TICKER>_<YYYY-MM-DD>_<shortid>.html"` (date in IST).
- `?print=1`: served inline and calls `window.print()` on load; use the browser's "Save as PDF" (A4 print CSS).
- Same owner auth as `GET /api/runs/{run_id}`: 401 without a session, 404 for unknown or other owners' runs, 409 while QUEUED/RUNNING. FAILED and INTERRUPTED runs render what was recorded.
- Missing data renders as "Not recorded for this run". Runs created before price persistence have no price chart; new live runs write `processed/market/<ticker>_price_history.parquet` (last 260 closes plus SMA 20/50) from the `get_price_history` MCP tool.
- All text is HTML-escaped; only http(s) links are rendered as links.
