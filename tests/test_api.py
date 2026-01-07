from unittest.mock import patch
from fastapi.testclient import TestClient # pyright: ignore[reportMissingImports]
from src.api.main import app

# Create a test client (like a fake web browser)
client = TestClient(app)

def test_health_check():
    """
    Verifies the API is running and returns the correct health message.
    """
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "Scraper API is running"}

def test_get_docs():
    """
    Verifies the Swagger UI endpoint is reachable.
    """
    response = client.get("/docs")
    assert response.status_code == 200

# New: Semantic Memory Search Endpoint Test
@patch('src.api.main.search_memory')
def test_search_memory_endpoint(mock_search):
    """
    Verifies the Memory Search endpoint returns the correct JSON structure.
    We mock the actual DB lookup to keep it fast and isolated.
    """
    # 1. Setup Mock Return Value (What the DB 'would' return)
    # We simulate a "ScrapedData" object using a simple class or dict
    class MockArticle:
        id = 10
        title = "AI Revolution"
        url = "http://ai.com"
        summary = "AI is changing everything"
        ai_category = "Tech"
    
    mock_search.return_value = [MockArticle()]

    # 2. Call the API
    response = client.get("/api/v1/memory/search?q=future&limit=1")

    # 3. Assertions
    assert response.status_code == 200
    data = response.json()
    
    assert data['query'] == "future"
    assert data['count'] == 1
    assert data['results'][0]['title'] == "AI Revolution"
    
    # Ensure our mock was actually called with the right params
    mock_search.assert_called_once_with("future", limit=1)