from fastapi.testclient import TestClient

from bullbear.server import app

client = TestClient(app)


def test_health_and_auth():
    assert client.get("/health").json() == {"status": "UP"}
    assert client.get("/stocks/005930").json()["error"]["code"] == "UNAUTHORIZED"


def test_endpoints_are_not_implemented_yet():
    res = client.get("/stocks/005930", headers={"X-Worker-Token": "dev-worker-token"})
    assert res.status_code == 501 and res.json()["error"]["code"] == "NOT_IMPLEMENTED"
