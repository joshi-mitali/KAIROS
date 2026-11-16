from unittest.mock import Mock, patch
from types import SimpleNamespace
import pandas as pd
import pytest
from kairos.providers.yahoo import fetch_yahoo, YahooUnavailable
from kairos.trading.market import MarketFeed


def test_transient_outage_recovers_without_unbounded_retries():
    fetch=Mock(side_effect=[RuntimeError('*** YAHOO! FINANCE IS CURRENTLY DOWN! ***'),['fresh']])
    with patch('kairos.providers.yahoo.time.sleep'):
        assert fetch_yahoo('news',fetch)==['fresh']
    assert fetch.call_count==2


def test_permanent_failure_is_bounded_and_actionable():
    fetch=Mock(side_effect=RuntimeError('*** YAHOO! FINANCE IS CURRENTLY DOWN! ***'))
    with patch('kairos.providers.yahoo.time.sleep'),pytest.raises(YahooUnavailable,match='news is temporarily unavailable') as error:
        fetch_yahoo('news',fetch)
    assert fetch.call_count==2
    assert 'CURRENTLY DOWN' not in str(error.value)


def test_empty_history_is_not_success_or_archived_data():
    fetch=Mock(return_value=pd.DataFrame())
    with patch('kairos.providers.yahoo.time.sleep'),pytest.raises(YahooUnavailable):
        fetch_yahoo('history',fetch,valid=lambda frame:not frame.empty)
    assert fetch.call_count==2


def test_search_falls_back_to_exchange_verified_broker_instruments():
    client=Mock()
    client.instruments.return_value=[{'tradingSymbol':'RELIANCE','instrumentName':'Reliance Industries','instrumentToken':'123'}]
    client.quote.return_value={'exchange':'BSE','ltp':100}
    with patch('yfinance.Search',side_effect=RuntimeError('down')),patch('kairos.providers.yahoo.time.sleep'):
        rows=MarketFeed(client).search('reliance')
    assert rows==[{'symbol':'RELIANCE.BO','ticker':'RELIANCE','exchange':'BSE','name':'Reliance Industries','source':'MEGABULL'}]


def test_unknown_exchange_is_not_guessed_in_search():
    client=Mock();client.instruments.return_value=[{'tradingSymbol':'RELIANCE','instrumentToken':'123'}]
    client.quote.return_value={'ltp':100}
    with patch('yfinance.Search',side_effect=RuntimeError('down')),patch('kairos.providers.yahoo.time.sleep'):
        assert MarketFeed(client).search('reliance')==[]


def test_quote_feed_does_not_call_yahoo_during_outage():
    client=Mock();client.resolve_instrument.return_value='token';client.quote.return_value={'ltp':1200,'exchange':'NSE'}
    with patch('yfinance.Ticker',side_effect=RuntimeError('down')):
        assert MarketFeed(client).quote('RELIANCE')['ltp']==1200


def test_quote_network_error_does_not_imply_an_order_was_sent():
    import requests
    from kairos.trading.megabull import MegabullClient
    session=Mock();session.request.side_effect=requests.ConnectionError('offline')
    with pytest.raises(ValueError,match='Retry the data feed later'):
        MegabullClient(api_key='test',session=session).quote('123')
