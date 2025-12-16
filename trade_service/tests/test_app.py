import pytest
from src.app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_health(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert b"healthy" in response.data

def test_create_trade(client):
    response = client.post('/trades', json={"trade_id": "test123", "symbol": "AAPL", "quantity": 10, "price": 150.0, "trade_type": "buy"})
    assert response.status_code == 201