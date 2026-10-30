import io
import json
import zipfile

import httpx
import pytest

from bullbear.data.base import DataUnavailable
from bullbear.data.opendart import OpenDartClient


KEY = "private-test-key"
PARAMS = {"corp_code": "00126380", "bsns_year": "2026", "reprt_code": "11014"}
REPORT = {"status": "000", "list": [{"rcept_no": "20261116000001"}]}


@pytest.fixture
def client_for(tmp_path):
    clients = []

    def make(handler):
        client = OpenDartClient(KEY, tmp_path)
        client._http.close()
        client._http = httpx.Client(base_url="https://example.test/api", transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield make
    for client in clients:
        client._http.close()


def report_cache(tmp_path):
    path = tmp_path / "fnlttSinglAcnt" / "bsns_year=2026_corp_code=00126380_reprt_code=11014.json"
    path.parent.mkdir(exist_ok=True)
    return path


def companies_zip(xml=None, *, name="CORPCODE.xml"):
    if xml is None:
        xml = """<result><list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
          <stock_code>005930</stock_code></list></result>"""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, xml)
    return output.getvalue()


def test_no_data_is_not_cached_and_published_report_is_cached(tmp_path, client_for):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"status": "013"} if len(calls) == 1 else REPORT)

    client = client_for(handle)
    assert client.get("fnlttSinglAcnt", **PARAMS) is None
    assert not list(tmp_path.rglob("*.json"))
    assert client.get("fnlttSinglAcnt", **PARAMS) == REPORT
    assert client.get("fnlttSinglAcnt", **PARAMS) == REPORT
    assert len(calls) == 2


def test_legacy_no_data_cache_is_refreshed(tmp_path, client_for):
    path = report_cache(tmp_path)
    path.write_text(json.dumps({"status": "013"}), encoding="utf-8")
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=REPORT)

    client = client_for(handle)
    assert client.get("fnlttSinglAcnt", **PARAMS) == REPORT
    assert len(calls) == 1
    assert json.loads(path.read_text(encoding="utf-8")) == REPORT


@pytest.mark.parametrize("contents", ["{broken", "[]", '{"status":"000","list":null}'])
def test_damaged_report_cache_is_refetched(tmp_path, client_for, contents):
    report_cache(tmp_path).write_text(contents, encoding="utf-8")
    client = client_for(lambda request: httpx.Response(200, json=REPORT))
    assert client.get("fnlttSinglAcnt", **PARAMS) == REPORT


@pytest.mark.parametrize("response", [
    httpx.Response(503, text=KEY),
    httpx.Response(200, text=KEY),
    httpx.Response(200, json=[]),
    httpx.Response(200, json={"status": "000", "list": [None]}),
    httpx.Response(200, json={"status": "010", "message": KEY}),
])
def test_invalid_report_response_is_safe_and_not_cached(tmp_path, client_for, response):
    client = client_for(lambda request: response)
    with pytest.raises(DataUnavailable) as error:
        client.get("fnlttSinglAcnt", **PARAMS)
    assert KEY not in str(error.value)
    assert not list(tmp_path.rglob("*.json"))


@pytest.mark.parametrize("method", ["report", "corp_code", "listed_companies"])
@pytest.mark.parametrize("exception", [httpx.ReadTimeout, httpx.ConnectError])
def test_network_errors_are_data_unavailable(client_for, method, exception):
    def handle(request):
        raise exception(KEY, request=request)

    client = client_for(handle)
    with pytest.raises(DataUnavailable) as error:
        if method == "report":
            client.get("fnlttSinglAcnt", **PARAMS)
        elif method == "corp_code":
            client.corp_code("005930")
        else:
            client.listed_companies()
    assert KEY not in str(error.value)


@pytest.mark.parametrize("first", ["corp_code", "listed_companies"])
def test_company_download_populates_both_caches(client_for, first):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=companies_zip())

    client = client_for(handle)
    if first == "corp_code":
        assert client.corp_code("005930") == "00126380"
    else:
        assert client.listed_companies() == {"005930": "삼성전자"}
    assert client.corp_code("005930") == "00126380"
    assert client.listed_companies() == {"005930": "삼성전자"}
    # A new process/client can also use either successful cache without a request.
    cached = client_for(lambda request: pytest.fail("unexpected company download"))
    assert cached.corp_code("005930") == "00126380"
    assert cached.listed_companies() == {"005930": "삼성전자"}
    assert len(calls) == 1


@pytest.mark.parametrize("contents", ["{broken", "[]", '{"005930":null}'])
@pytest.mark.parametrize("method,filename", [("corp_code", "corp_codes.json"), ("listed_companies", "listed_companies.json")])
def test_damaged_company_cache_is_refetched(tmp_path, client_for, contents, method, filename):
    (tmp_path / filename).write_text(contents, encoding="utf-8")
    client = client_for(lambda request: httpx.Response(200, content=companies_zip()))
    if method == "corp_code":
        assert client.corp_code("005930") == "00126380"
    else:
        assert client.listed_companies() == {"005930": "삼성전자"}


@pytest.mark.parametrize("response", [
    httpx.Response(401, text=KEY),
    httpx.Response(200, content=KEY.encode()),
    httpx.Response(200, content=companies_zip("<broken")),
    httpx.Response(200, content=companies_zip(name="missing.xml")),
    httpx.Response(200, content=companies_zip("<result/>")),
    httpx.Response(200, content=companies_zip("<result><list><stock_code>005930</stock_code></list></result>")),
])
@pytest.mark.parametrize("method", ["corp_code", "listed_companies"])
def test_company_http_zip_xml_errors_are_safe(client_for, response, method):
    client = client_for(lambda request: response)
    with pytest.raises(DataUnavailable) as error:
        if method == "corp_code":
            client.corp_code("005930")
        else:
            client.listed_companies()
    assert KEY not in str(error.value)


def test_cache_false_always_refetches(client_for):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=REPORT)

    client = client_for(handle)
    assert client.get("fnlttSinglAcnt", **PARAMS) == REPORT
    assert client.get("fnlttSinglAcnt", cache=False, **PARAMS) == REPORT
    assert len(calls) == 2
