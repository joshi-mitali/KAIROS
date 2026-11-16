"""Approval and at-most-once behavior; no calls to a paper trading account."""
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kairos.trading.approval import PaperApprovalService
from kairos.trading.megabull import PaperOrder


@pytest.fixture
def service():
    with tempfile.TemporaryDirectory() as tmp:
        client = MagicMock()
        client.resolve_instrument.return_value = "1234"
        client.quote.return_value = {"ltp": 1200, "exchange":"NSE"}
        client.account.return_value = {"virtualMoneyLeft": 500000}
        client.submit.return_value = {"id": 123, "status": "PENDING"}
        yield PaperApprovalService(Path(tmp) / "orders.db", client)


def order(**overrides):
    return PaperOrder(ticker="RELIANCE", side="BUY", quantity=2, price=1200, **overrides)


def test_preview_does_not_submit_and_approval_executes_exact_preview(service):
    preview = service.preview(order(), "owner")
    service.client.submit.assert_not_called()
    assert preview["status"] == "AWAITING_APPROVAL"
    result = service.approve(preview["approval_id"], preview["approval_token"], "owner")
    assert result["provider_order"]["id"] == 123
    service.client.submit.assert_called_once()
    submitted, instrument = service.client.submit.call_args.args
    assert submitted == order() and instrument == "1234"
    assert "approval_token" not in str(service.history("owner"))


def test_cross_session_bad_token_and_expiry_cannot_submit(service):
    preview = service.preview(order(), "owner")
    for token, owner in [(preview["approval_token"], "other"), ("wrong", "owner")]:
        with pytest.raises(ValueError):
            service.approve(preview["approval_id"], token, owner)
    with service.connect() as db:
        db.execute("UPDATE paper_approvals SET expires=0")
    with pytest.raises(ValueError, match="expired"):
        service.approve(preview["approval_id"], preview["approval_token"], "owner")
    service.client.submit.assert_not_called()


def test_duplicate_approval_is_never_resubmitted(service):
    preview = service.preview(order(), "owner")
    service.approve(preview["approval_id"], preview["approval_token"], "owner")
    with pytest.raises(ValueError, match="already"):
        service.approve(preview["approval_id"], preview["approval_token"], "owner")
    service.client.submit.assert_called_once()


def test_ambiguous_network_failure_requires_reconciliation(service):
    preview = service.preview(order(), "owner")
    service.client.submit.side_effect = TimeoutError("unknown whether accepted")
    with pytest.raises(ValueError, match="automatic retries are disabled"):
        service.approve(preview["approval_id"], preview["approval_token"], "owner")
    assert service.history("owner")[0]["status"] == "REVIEW_REQUIRED"
    with pytest.raises(ValueError):
        service.approve(preview["approval_id"], preview["approval_token"], "owner")
    service.client.submit.assert_called_once()


@pytest.mark.parametrize("updates", [{"quantity": True}, {"quantity": 0}, {"quantity": 10000}, {"price": float("nan")}, {"price": None}, {"ticker": "../bad"}])
def test_invalid_paper_orders_are_rejected(updates):
    values = dict(ticker="RELIANCE", side="BUY", quantity=2, price=1200)
    values.update(updates)
    with pytest.raises(ValueError):
        PaperOrder(**values)
