import pytest
from fastapi.testclient import TestClient
from src.api.server import app

@pytest.fixture
def client():
    return TestClient(app)

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "service" in response.json()

def test_schema_endpoint(client):
    response = client.get("/schema")
    assert response.status_code == 200
    assert "$defs" in response.json()

