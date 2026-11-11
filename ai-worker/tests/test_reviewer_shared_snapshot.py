import csv
import json
from io import StringIO

from bullbear.news_lookup import NewsLookup
from bullbear.statement_review import review_statement
from .graph_fakes import GraphLLM
from .prompt_helpers import initial_payload
from .test_graph_runtime import snapshot, runtime
from .test_statement_review import review_candidate, revised_review


def test_all_reviewers_receive_the_exact_speaker_common_prefix(snapshot, tmp_path):
    run = runtime(snapshot, tmp_path)
    reviewers = {side: GraphLLM(snapshot) for side in ('bull', 'bear')}
    run.statement_reviewers = reviewers
    run.run()
    for side, speaker in (('bull', run.bull), ('bear', run.bear)):
        assert len(reviewers[side].calls) == 3
        for (review_conv, _), (speaker_conv, _) in zip(reviewers[side].calls, speaker.calls, strict=True):
            assert review_conv.messages[0] == speaker_conv.messages[0]
            common = initial_payload(review_conv)['shared_push']
            rows = {r['source_id']: r for r in csv.DictReader(StringIO(common['facts_csv']))}
            assert rows['PX.CLOSE']['value'] == str(int(snapshot.facts['PX.CLOSE'].value))
            assert 'PX.MA200' in rows
            assert any(key.startswith('FIN.') for key in rows)
            assert 'data_status' in common and 'warnings' in common


def test_reviewer_can_use_common_fact_not_cited_by_speaker(snapshot):
    candidate = review_candidate(snapshot)
    candidate.evidence[0].source_id = 'PX.MA200'
    candidate.evidence[0].value = snapshot.facts['PX.MA200'].value

    class Reviewer:
        def structured(self, conv, **kwargs):
            payload = initial_payload(conv)
            rows = {r['source_id']: r for r in csv.DictReader(StringIO(payload['shared_push']['facts_csv']))}
            assert 'PX.CLOSE' in rows and 'PX.MA200' in rows
            assert '자료가 없다고 주장하기 전에' in payload['review_instructions']
            return conv.context_ids.encode_context(revised_review(candidate, sources=('PX.CLOSE',)))

    result = review_statement(Reviewer(), candidate, snapshot, [], effort='high')
    assert result.issues[0].source_ids == ['PX.CLOSE']
    assert result.revised_statement is not None


def test_reviewer_fetches_missing_fact_with_alias_then_uses_it_in_edit(snapshot):
    snapshot.facts['PX.EXTRA'] = snapshot.facts['PX.CLOSE'].model_copy(update={'id': 'PX.EXTRA', 'value': 42})
    candidate = review_candidate(snapshot)

    class Reviewer:
        def structured(self, conv, **kwargs):
            payload = initial_payload(conv)
            alias = conv.context_ids.fact_ids['PX.EXTRA']
            assert alias not in conv.messages[0]['content'][0]['text']
            assert 'PX.EXTRA' not in payload['facts_csv']
            handle = kwargs['tool_handler']
            catalog = json.loads(handle('read_snapshot', {'kind': 'catalog', 'args': ['price', '0']}))
            assert catalog
            chart = json.loads(handle('read_snapshot', {'kind': 'chart', 'args': [str(snapshot.as_of)] * 2}))
            assert 'daily_ohlcv_csv' in chart
            fetched = json.loads(handle('read_snapshot', {'kind': 'facts', 'args': [alias]}))
            assert next(csv.DictReader(StringIO(fetched['facts_csv'])))['source_id'] == alias
            response = revised_review(candidate, sources=('PX.EXTRA',))
            response['edits'] = [{'path': 'evidence.0.source_id', 'value': 'PX.EXTRA'},
                                 {'path': 'evidence.0.value', 'value': 42.0}]
            return conv.context_ids.encode_context(response)

    result = review_statement(Reviewer(), candidate, snapshot, [], effort='high')
    assert result.revised_statement.evidence[0].source_id == 'PX.EXTRA'
    assert result.revised_statement.evidence[0].value == 42


def test_reviewer_news_lookup_updates_shared_news_state():
    from .test_news_lookup import article_snapshot, fetch_blocks, MODEL, BODY
    snapshot, article = article_snapshot()
    candidate = review_candidate(snapshot)
    news = NewsLookup(snapshot, enabled=True, require_summary_lookup=True)

    class Reviewer:
        model = MODEL

        def structured(self, conv, **kwargs):
            assert 'web_fetch' in {tool['name'] for tool in kwargs['tools']}
            alias = conv.context_ids.fact_ids[article.id]
            summaries = json.loads(kwargs['tool_handler']('read_snapshot',
                {'kind': 'facts', 'args': [alias]}))
            assert article.note in summaries['facts_csv']
            result = json.loads(kwargs['tool_handler']('get_new_url', {'source_id': alias}))
            assert result['url'] == article.url and result['summary'] == article.note
            requested, fetched = fetch_blocks(article.url, True)
            kwargs['on_event'](requested['type'], requested)
            kwargs['on_event'](fetched['type'], fetched)
            response = revised_review(candidate, sources=(article.id,))
            return conv.context_ids.encode_context(response)

    result = review_statement(Reviewer(), candidate, snapshot, [], effort='high',
                              news_lookup=news, news_results=news.results)
    assert result.issues[0].source_ids == [article.id]
    assert news.results[article.id]['status'] == 'body'
    assert news.results[article.id]['text'] == BODY
