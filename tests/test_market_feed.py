from unittest.mock import Mock
import pytest
from kairos.trading.market import MarketFeed,normalize_symbol
from kairos.trading.megabull import PaperOrder


def test_exchange_aware_symbols():
    assert normalize_symbol('M&M')=='M&M.NS'
    assert normalize_symbol('500325.BO')=='500325.BO'
    with pytest.raises(ValueError):normalize_symbol('../bad')
    with pytest.raises(ValueError):PaperOrder(ticker='500325.BO',exchange='NSE',side='BUY',quantity=1,price=100)


def test_quote_is_cached_validated_and_never_fabricated():
    client=Mock();client.resolve_instrument.return_value='token'
    client.quote.return_value={'ltp':1200,'exchange':'BSE'}
    feed=MarketFeed(client)
    first=feed.quote('500325.BO');second=feed.quote('500325.BO')
    assert first['ltp']==1200 and len(second['points'])==1
    client.quote.assert_called_once()
    client.resolve_instrument.assert_called_once_with('500325.BO','BSE')
    assert first['exchange_timestamp'] is None


def test_quote_exchange_mismatch_is_blocked():
    client=Mock();client.quote.return_value={'ltp':100,'exchange':'NSE'}
    with pytest.raises(ValueError,match='exchange'):MarketFeed(client).quote('500325.BO')
