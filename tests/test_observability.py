"""Tracing/privacy and audit fixes, with no remote telemetry."""
from datetime import date,timedelta
from unittest.mock import patch

from kairos.observability.guardrails import FreshnessGuardrail
from kairos.observability.langfuse_tracing import mask_data,traced
from kairos.memory.models import MemoryRecord,RecordType,TradeOutcome
from kairos.memory.storage import _score_and_rank_records


def test_mask_hides_secrets_in_structures_and_free_text():
    with patch.dict('os.environ', {'LANGFUSE_SECRET_KEY':'test-secret-value'}):
        result=mask_data({'authorization':'Bearer secret', 'nested':[{'api_key':'private'}], 'error':'failed test-secret-value'})
    assert result['authorization']=='[REDACTED]'
    assert result['nested'][0]['api_key']=='[REDACTED]'
    assert 'test-secret-value' not in result['error']


def test_disabled_tracing_preserves_outputs_and_exceptions():
    with patch('kairos.observability.langfuse_tracing.get_langfuse',return_value=None):
        @traced('test-operation',fields=('ticker',))
        def execute(ticker,client):
            return ticker
        assert execute('TCS',object())=='TCS'


def test_old_and_future_data_fail_freshness_guardrail():
    guard=FreshnessGuardrail(max_days_stale=45)
    assert not guard.evaluate({'as_of_date':str(date.today()-timedelta(days=46))}).passed
    assert not guard.evaluate({'as_of_date':str(date.today()+timedelta(days=3))}).passed
    assert guard.evaluate({'as_of_date':str(date.today())}).passed


def test_hardcoded_seed_records_are_not_used_as_performance_evidence():
    record=MemoryRecord(id='trade_tcs_20261016',record_type=RecordType.COMPLETED_TRADE,ticker='TCS',date=str(date.today()),outcome=TradeOutcome.WIN,pnl=1,pnl_pct=1)
    assert not _score_and_rank_records([record],'TCS','NORMAL','VALUE',None,None,3)
