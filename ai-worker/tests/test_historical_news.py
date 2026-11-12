from dataclasses import replace
from datetime import datetime, timedelta
from email.utils import format_datetime

import httpx
from bullbear.data.base import NewsArticle
from bullbear.data.naver_news import NaverNewsSource
from bullbear.data.news_selection import select_news
from bullbear.snapshot import KST, build_snapshot
from bullbear.server.store import Store
from .fakes import FakeSource, NOW

END = datetime(2026, 9, 1, 15, 30, tzinfo=KST)
START = END - timedelta(days=7)
SUMMARY = '시장조사업체 집계에 따르면 해당 기업은 올해 상반기 글로벌 게이밍 모니터 시장에서 금액 기준 17.8%의 점유율을 기록했다. 새로운 제품군을 통해 글로벌 시장에서 기술 경쟁력을 강화할 계획이다.'


def article(title='가상전자 게임스컴 오디세이 모니터 신제품 공개', summary=SUMMARY, url='https://news.test/1'):
    return NewsArticle(url, END-timedelta(days=2), title, summary, url)


def test_event_dedup_preserves_different_events():
    a=article()
    b=article('가상전자, 오디세이 모니터로 게임스컴 공략', '한편 '+SUMMARY, 'https://news.test/2')
    c=article('가상전자 반도체 공장 투자 확대', SUMMARY, 'https://news.test/3')
    d=article('가상전자 게임스컴 오디세이 모니터 가격 인상', '원재료 가격 급등으로 판매가를 높인다. ' * 8, 'https://news.test/4')
    out=select_news([a,b,c,d],START,END,limit=30,scope='company',event_dedupe=True)
    urls={v.url for v,_ in out}
    assert len(urls)==3
    assert c.url in urls and d.url in urls
    assert len(urls & {a.url,b.url})==1
    # Existing live selection is unchanged.
    assert len(select_news([a,b],START,END,limit=30,scope='company'))==2
    assert len(select_news([a,b],START,END,limit=30,scope='market',already_selected=[a],event_dedupe=True))==0


def test_historical_query_filters_publication_and_dedupes_queries():
    calls=[]
    source=NaverNewsSource('test','test')
    source._http.close()
    def row(title,url,when):
        return dict(title=title,originallink=url,link=url,description=SUMMARY,pubDate=format_datetime(when))
    def respond(request):
        calls.append(dict(request.url.params))
        return httpx.Response(200,json={'items':[
            row('삼성전자 장중 소식','https://news.test/ok',END-timedelta(seconds=1)),
            row('삼성전자 장마감 이후','https://news.test/future',END+timedelta(seconds=1)),
            row('삼성전자 오래된 소식','https://news.test/old',START-timedelta(seconds=1)),
            row('다른 기업 소식','https://news.test/other',END),
        ]})
    source._http=httpx.Client(transport=httpx.MockTransport(respond))
    try:
        out=source.search_historical('005930','삼성전자',START,END)
    finally: source.close()
    assert [v.url for v in out]==['https://news.test/ok']
    assert {c['query'] for c in calls}=={'2026 09 01 삼성전자','2026 상반기 삼성전자','2026 하반기 삼성전자'}
    assert all(c['sort']=='sim' for c in calls)


def test_builder_filters_future_news_even_if_source_does_not():
    class News:
        name='fake-history'
        def search(self,*args): raise AssertionError('live search')
        def search_market(self,*args): raise AssertionError('live market search')
        def search_historical(self,*args):
            return [article(),replace(article(),url='https://news.test/future',source_ref='future',published_at=END+timedelta(seconds=1))]
        def search_market_historical(self,*args):
            return [article('가상전자, 오디세이 모니터로 게임스컴 공략', '한편 '+SUMMARY,'https://news.test/repost')]
    snap=build_snapshot(FakeSource(),'005930','삼성전자',now=NOW,as_of=END.date(),news=News())
    news=snap.by_category('news')
    assert len(news)==1
    assert news[0].published_at<=END
    assert snap.data_policy=='historical_news_v1'
    assert snap.data_status['stock_news']=='OK'
    assert snap.data_status['market_news']=='EMPTY'


def test_new_news_policy_does_not_reuse_old_no_news_debate(tmp_path):
    store=Store(tmp_path)
    try:
        old,_=store.create('old','old','005930','2026-09-01',3,data_policy='historical')
        new,reused=store.create('new','new','005930','2026-09-01',3,data_policy='historical_news_v1')
        assert not reused and old['id']!=new['id']
        again,reused=store.create('again','again','005930','2026-09-01',3,data_policy='historical_news_v1')
        assert reused and again['id']==new['id']
    finally: store.close()
