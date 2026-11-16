import time
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from kairos.providers.groq import GroqKeyPool, GroqPoolClient, GroqCooldownError, get_key_pool
from kairos.observability.langfuse_tracing import mask_data
from kairos.observability import prompt_guard as guard


def test_pool_rotates_and_honors_cooldown(monkeypatch):
    pool=GroqKeyPool(['key-one','key-two','key-one'])
    assert len(pool.keys)==2
    error=Exception('rate limit');error.response=SimpleNamespace(headers={'retry-after':'60'})
    pool.rate_limited(pool.current(),error)
    assert pool.current()=='key-two'
    pool.rate_limited(pool.current(),error)
    with pytest.raises(GroqCooldownError):pool.current()
    pool.cooldowns['key-one']=time.monotonic()-1
    assert pool.current()=='key-one'


def test_client_rotates_only_429(monkeypatch):
    pool=GroqKeyPool(['first','second'])
    monkeypatch.setattr('kairos.providers.groq.get_key_pool',lambda:pool)
    rate=Exception('limit');rate.status_code=429
    first=Mock();first.chat.completions.create.side_effect=rate
    second=Mock();second.chat.completions.create.return_value='result'
    client=GroqPoolClient();client.clients={'first':first,'second':second}
    assert client.create(model='test')=='result'
    assert first.chat.completions.create.call_count==1
    assert second.chat.completions.create.call_count==1
    second.chat.completions.create.side_effect=ValueError('bad payload')
    with pytest.raises(ValueError):client.create(model='test')


def test_pool_secrets_are_redacted(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEYS','private-key-one,private-key-two')
    assert mask_data('one private-key-one two private-key-two')=='one [REDACTED] two [REDACTED]'


def test_guard_checks_later_chunks_and_fails_closed(monkeypatch):
    monkeypatch.setenv('KAIROS_PROMPT_GUARD_ENABLED','true')
    monkeypatch.setattr(guard,'_scan',lambda model,threshold,text: .99 if 'INJECT' in text else .01)
    with pytest.raises(guard.PromptGuardBlocked):guard.guard_untrusted_text('safe '*100+'INJECT','test')
    def unavailable(*args):raise RuntimeError('unavailable')
    monkeypatch.setattr(guard,'_scan',unavailable)
    with pytest.raises(guard.PromptGuardUnavailable):guard.guard_untrusted_text('safe','test')


def test_guard_enforces_input_budget(monkeypatch):
    monkeypatch.setenv('KAIROS_PROMPT_GUARD_ENABLED','true')
    with pytest.raises(guard.PromptGuardBlocked):guard.guard_untrusted_text('x'*20000,'test')


def test_model_cannot_rewrite_evidence_dates_counts_or_ticker():
    from kairos.agents.adk_analysts.base_analyst import ground_model_output
    from kairos.schemas.analyst_reports import SentimentAnalysisReport
    original=SentimentAnalysisReport(ticker='RELIANCE',overall_sentiment='NEUTRAL',sentiment_score=0,sample_size_posts=3,ticker_specific_posts_count=3,macro_context_posts_count=0,retail_bull_ratio=.5)
    result=ground_model_output({'ticker':'FAKE','generated_at':'2024-01-01','sample_size_posts':999,'key_themes':['Growth discussion']},SentimentAnalysisReport,original)
    assert result.ticker=='RELIANCE' and result.generated_at==original.generated_at
    assert result.sample_size_posts==3 and result.key_themes==['Growth discussion']


def test_streamed_debate_events_preserve_role_and_draft():
    from unittest.mock import Mock
    from kairos.web.runs import EventCallback
    store=Mock();callback=EventCallback(store,'run')
    callback.on_research_stream('Bull Researcher','task','actual chunk','trace')
    store.emit.assert_called_once_with('run','debate-stream',{'agent':'Bull Researcher','task_id':'task','text':'actual chunk'})


def test_guard_scan_retries_one_stalled_request(monkeypatch):
    import httpx, openai
    from types import SimpleNamespace
    calls = []
    def create(**kwargs):
        calls.append(kwargs["timeout"])
        if len(calls) == 1:
            raise openai.APITimeoutError(httpx.Request("POST", "https://x"))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="0.02"))])
    monkeypatch.setattr(guard, "_client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    guard._scan.cache_clear()
    assert guard._scan("m", .5, "retry-me") == .02 and len(calls) == 2
    guard._scan.cache_clear()
