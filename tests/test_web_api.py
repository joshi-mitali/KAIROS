from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from kairos.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('KAIROS_WEB_PASSWORD',raising=False)
    paper=Mock();paper.account.return_value={'virtualMoneyLeft':100000}
    app=create_app(data_dir=tmp_path,runtime_dir=tmp_path/'runtime',paper_client=paper)
    app.state.runs.worker.submit=Mock()
    with TestClient(app) as client:
        yield client


def login(client):
    assert client.post('/api/session',json={}).status_code==200


def test_auth_origin_and_jsonc(client):
    assert client.get('/api/runs').status_code==401
    assert client.post('/api/session',json={},headers={'Origin':'https://evil.example'}).status_code==403
    login(client)
    config=client.get('/api/config')
    assert config.status_code==200 and len(config.json()['agents'])==8
    assert client.get('/api/not-an-endpoint').status_code==404


def test_run_isolation_and_bounded_queue(client):
    login(client)
    response=client.post('/api/runs',json={'ticker':'RELIANCE','source':'live'})
    assert response.status_code==202
    run_id=response.json()['id']
    assert client.post('/api/runs',json={'ticker':'TCS'}).status_code==409
    assert client.get('/api/runs/'+run_id).status_code==200
    client.cookies.clear();login(client)
    assert client.get('/api/runs/'+run_id).status_code==404
    assert client.get('/api/runs/'+run_id+'/events').status_code==404


@pytest.mark.parametrize('approved',[False,1,'true',None])
def test_approval_must_be_explicit_boolean(client,approved):
    login(client)
    response=client.post('/api/paper/approvals/missing',json={'approval_token':'token','approved':approved})
    assert response.status_code==422
    client.app.state.paper.client.submit.assert_not_called()


def test_market_missing_is_clear(client,monkeypatch):
    monkeypatch.setattr('kairos.trading.market.MarketFeed.candles',Mock(side_effect=ValueError('Unavailable')))
    login(client)
    assert client.get('/api/market/RELIANCE').status_code==502
    assert client.get('/api/market/UNKNOWN').status_code==502


def test_archived_source_cannot_start_new_run(client):
    login(client)
    assert client.post('/api/runs',json={'ticker':'RELIANCE','source':'saved'}).status_code==422


def test_bse_listing_is_preserved(client):
    login(client)
    response=client.post('/api/runs',json={'ticker':'500325.BO'})
    assert response.status_code==202
    assert client.get('/api/runs/'+response.json()['id']).json()['ticker']=='500325.BO'
