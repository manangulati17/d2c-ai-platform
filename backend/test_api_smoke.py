"""
Smoke test for Phase 6 API routes.

Tests that all endpoints are accessible and return expected status codes.
Does NOT test actual functionality (that's for Phase 8 testing).
"""

import sys
from fastapi.testclient import TestClient

# Add backend to path
sys.path.insert(0, '/Users/manan/Desktop/shiprocket/d2c-ai-platform/backend')

from main import app

client = TestClient(app)


def test_root():
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "D2C AI Platform API"
    assert data["version"] == "0.1.0"
    print("✓ Root endpoint works")


def test_health():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    print("✓ Health check endpoint works")


def test_merchants_list():
    """Test merchants list endpoint."""
    response = client.get("/merchants/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    print("✓ Merchants list endpoint works")


def test_openapi_docs():
    """Test that OpenAPI docs are accessible."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    docs = response.json()
    assert docs["info"]["title"] == "D2C AI Platform"
    assert docs["info"]["version"] == "0.1.0"
    print("✓ OpenAPI docs accessible")


def test_route_count():
    """Test that all expected routes are registered."""
    response = client.get("/openapi.json")
    docs = response.json()
    paths = docs["paths"]
    
    # Expected endpoints
    expected = [
        "/",
        "/health",
        "/merchants/",
        "/merchants/{merchant_id}",
        "/merchants/{merchant_id}/connectors",
        "/merchants/{merchant_id}/connectors/{source}/sync",
        "/merchants/{merchant_id}/connectors/{source}/status",
        "/chat/",
        "/merchants/{merchant_id}/agent/logs",
        "/merchants/{merchant_id}/agent/logs/{log_id}",
        "/merchants/{merchant_id}/agent/run",
    ]
    
    for path in expected:
        assert path in paths, f"Expected path {path} not found in OpenAPI docs"
    
    print(f"✓ All {len(expected)} expected endpoints registered")


if __name__ == "__main__":
    print("\n=== Phase 6 API Smoke Test ===\n")
    
    try:
        test_root()
        test_health()
        test_merchants_list()
        test_openapi_docs()
        test_route_count()
        
        print("\n✓✓✓ All smoke tests passed! ✓✓✓\n")
        print("Phase 6: API Routes implementation complete and functional.")
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}\n")
        sys.exit(1)
