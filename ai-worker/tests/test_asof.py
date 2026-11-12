from datetime import date
import pytest
from fastapi.testclient import TestClient
from bullbear.snapshot import build_snapshot
from bullbear import cli
from .fakes import FakeSource, NOW
from .test_server import setup, app_for, start, completed, AUTH

class NoNews:
    name = "unsupported-historical-news"
    def search(self, *args):
        raise AssertionError('historical news called')

def test_historical_builder():
    snap = build_snapshot(FakeSource(), '005930', '삼성전자', now=NOW, as_of=date(2026,9,1), news=NoNews())
    assert snap.as_of == date(2026,9,1)
    assert snap.data_policy == 'historical_news_v1'
    assert snap.information_cutoff.hour == 15
    assert all(b.date <= snap.as_of for b in snap.series.stock_ohlcv)
    assert not snap.by_category('news')
    assert all(f.as_of <= snap.as_of for f in snap.facts.values())

def test_http_asof(setup):
    with TestClient(app_for(setup)) as c:
        quote=c.get('/stocks/005930?as_of=2026-09-01', headers=AUTH).json()
        r=start(c, as_of='2026-09-01').json()
        result=completed(c,r['debate_id'])
        assert result['status']=='completed'
        snap=c.get('/snapshots/'+result['snapshot_id'],headers=AUTH).json()
        assert snap['as_of']==quote['as_of']=='2026-09-01'
        assert snap['facts']['PX.CLOSE']['value']==quote['close']
        assert snap['data_policy']=='historical_news_v1'
        assert start(c,key='repeat',as_of='2026-09-01').json()['debate_id']==r['debate_id']
        assert start(c,as_of='2026-09-02').status_code==409
        assert start(c,key='future',as_of='2099-01-01').status_code==400
        assert c.get('/stocks/005930?as_of=bad',headers=AUTH).status_code==400

def test_live_not_reused(setup):
    with TestClient(app_for(setup)) as c:
        live=start(c).json()
        completed(c,live['debate_id'])
        past=start(c,key='past',as_of='2026-10-16').json()
        assert past['debate_id']!=live['debate_id']
        result=completed(c,past['debate_id'])
        single=start(c,key='single',mode='single',snapshot_id=result['snapshot_id']).json()
        assert completed(c,single['debate_id'])['status']=='completed'

def test_cli_date(monkeypatch):
    seen=[]
    monkeypatch.setattr(cli,'cmd_snapshot',lambda args,settings:seen.append(args.as_of))
    cli.main(['snapshot','삼성전자','--as-of','2026-09-01'])
    assert seen==[date(2026,9,1)]
    with pytest.raises(SystemExit): cli.main(['snapshot','삼성전자','--as-of','bad'])
    with pytest.raises(SystemExit): cli.main(['debate','삼성전자','--snapshot','id','--as-of','2026-09-01'])

def test_weekend_and_future_rows(setup):
    from datetime import timedelta
    settings, market = setup
    original = market.source.get_daily_prices
    market.source.get_daily_prices = lambda ticker,start,end: [b for b in original(ticker,start,NOW.date()) if b.date.weekday()<5]
    quote = market.quote('005930', as_of=date(2026,10,11))
    snap = market.snapshot(quote)
    assert snap.as_of == date(2026,10,9)
    assert all(b.date <= snap.as_of for b in snap.series.stock_ohlcv)
    market.now = lambda: NOW.replace(hour=15,minute=30)
    with pytest.raises(Exception) as error:
        market.quote('005930',as_of=NOW.date())
    assert error.value.code == 'INVALID_REQUEST'

def test_cli_builds_historical_snapshot(setup, monkeypatch, capsys):
    monkeypatch.setattr('bullbear.server.market.Market', lambda settings, **kwargs: setup[1])
    monkeypatch.setattr(cli, 'load_settings', lambda:setup[0])
    cli.main(['snapshot','삼성전자','--as-of','2026-09-01'])
    assert '2026-09-01' in capsys.readouterr().out
    assert list(setup[0].snapshot_dir.glob('005930-20260901-*.json'))

def test_historical_runner_blocks_live_news(setup):
    from bullbear.server.service import LiveRunner
    from .http_fixture import TestRunner
    seen=[]
    class SpyRunner(LiveRunner):
        def run(self,snapshot,debate_id,max_extra_rounds,emit):
            seen.append(self.live_news)
            return TestRunner(self.settings).run_single(snapshot,debate_id,emit)
    with TestClient(app_for(setup,runner_factory=lambda:SpyRunner(setup[0]))) as c:
        r=start(c,as_of='2026-09-01').json()
        assert completed(c,r['debate_id'])['status']=='completed'
    assert seen==[False]
