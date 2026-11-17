"""Persisted, expiring, session-bound approval gate with at-most-once submission."""

import hashlib
import json
import secrets
import time
from pathlib import Path

from kairos.storage.db import Database
from kairos.trading.megabull import MegabullClient, PaperOrder

APPROVAL_LOCK = 7421


class PaperApprovalService:
    def __init__(self, db_path: Path, client: MegabullClient):
        self.client = client
        self.db = Database(db_path)
        ddl = ["""CREATE TABLE IF NOT EXISTS paper_approvals (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, token_hash TEXT NOT NULL,
                order_json TEXT NOT NULL, instrument_token TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL,
                status TEXT NOT NULL, response_json TEXT, created DOUBLE PRECISION NOT NULL)"""]
        self.db.migrate([ddl[0].replace("DOUBLE PRECISION", "REAL")], ddl)

    def preview(self, order: PaperOrder, owner: str):
        instrument = self.client.resolve_instrument(order.ticker, order.exchange)
        quote = self.client.quote(instrument)
        if quote.get("exchange") != order.exchange:
            raise ValueError("Broker instrument exchange does not match the selected listing. This order cannot be approved.")
        account = self.client.account()
        approval_id, token = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        expires = time.time() + 300
        self.db.query("INSERT INTO paper_approvals VALUES (?,?,?,?,?,?,?,?,?)", (
            approval_id, owner, hashlib.sha256(token.encode()).hexdigest(), order.model_dump_json(),
            instrument, expires, "AWAITING_APPROVAL", None, time.time(),
        ))
        return {"approval_id": approval_id, "approval_token": token, "expires_at": expires,
                "order": order.model_dump(), "instrument_token": instrument, "quote": quote,
                "account": account, "environment": "PAPER", "status": "AWAITING_APPROVAL",
                "notice": "Only the entry order will be submitted. Proposal stop-loss and target are not automatic exit orders."}

    def approve(self, approval_id: str, token: str, owner: str):
        with self.db.tx(lock=APPROVAL_LOCK) as q:
            rows = q("SELECT * FROM paper_approvals WHERE id=? AND owner=?", (approval_id, owner))
            row = rows[0] if rows else None
            if not row or not secrets.compare_digest(row["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
                raise ValueError("This approval is invalid or belongs to another session.")
            if row["status"] != "AWAITING_APPROVAL":
                raise ValueError("This order has already been submitted or requires reconciliation; it cannot be resubmitted.")
            if row["expires"] < time.time():
                raise ValueError("The order preview expired. Review a fresh quote before approving.")
            # Commit before the network call. Provider has no documented idempotency key.
            q("UPDATE paper_approvals SET status='SUBMITTING' WHERE id=?", (approval_id,))
        try:
            result = self.client.submit(PaperOrder.model_validate_json(row["order_json"]), row["instrument_token"])
        except Exception:
            self.db.query("UPDATE paper_approvals SET status='REVIEW_REQUIRED' WHERE id=?", (approval_id,))
            raise ValueError("Submission could not be confirmed. Check the provider order list before preparing another order; automatic retries are disabled.") from None
        self.db.query("UPDATE paper_approvals SET status='SUBMITTED', response_json=? WHERE id=?", (json.dumps(result), approval_id))
        return {"approval_id": approval_id, "environment": "PAPER", "status": "SUBMITTED", "provider_order": result}

    def history(self, owner: str):
        rows = self.db.query("SELECT id,order_json,status,response_json,created FROM paper_approvals WHERE owner=? ORDER BY created DESC LIMIT 100", (owner,))
        return [{"id": r["id"], "order": json.loads(r["order_json"]), "status": r["status"],
                 "provider_order": json.loads(r["response_json"]) if r["response_json"] else None, "created": r["created"]} for r in rows]
