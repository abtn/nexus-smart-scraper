from unittest.mock import patch, MagicMock
from src.scraper.hunter import search_web

# 1. We mock 'DDGS' (DuckDuckGo) because that's the fallback logic we want to test
# 2. We mock 'TavilyClient' to ensure we test the fallback or primary path if keys exist
# 3. We NO LONGER mock 'is_allowed' because we removed it from hunter.py

@patch('src.scraper.hunter.DDGS')
@patch('src.scraper.hunter.is_useful_link', return_value=True) # Mock the usefulness filter
def test_search_web_success(mock_useful, mock_ddgs_cls):
    """
    Test that search_web parses results and filters correctly via DuckDuckGo fallback.
    """
    # 1. Setup Mock DDGS
    mock_ddgs_instance = mock_ddgs_cls.return_value
    mock_ddgs_instance.__enter__.return_value = mock_ddgs_instance
    
    # Mock results
    mock_ddgs_instance.text.return_value = [
        {"href": "https://valid.com/article", "title": "Good Article"},
        {"href": "https://youtube.com/watch?v=123", "title": "Video"} # Should be filtered by logic if logic was real, but here we mocked is_useful=True for simplicity or we can partial mock.
    ]

    # To test filtering, let's actually NOT mock is_useful_link globally, 
    # but since is_useful_link is simple, let's trust the logic or specific mock:
    # Actually, let's mock side_effect to simulate real filtering:
    def side_effect(url):
        return "youtube" not in url
    
    mock_useful.side_effect = side_effect

    # 2. Run Hunter
    results = search_web("test topic", max_results=5)

    # 3. Assertions
    # Should only contain the valid article
    assert len(results) == 1
    assert "https://valid.com/article" in results
    assert "https://youtube.com/watch?v=123" not in results

@patch('src.scraper.hunter.DDGS')
def test_search_web_no_results(mock_ddgs_cls):
    """Test handling of empty search results."""
    mock_ddgs_instance = mock_ddgs_cls.return_value
    mock_ddgs_instance.__enter__.return_value = mock_ddgs_instance
    mock_ddgs_instance.text.return_value = []

    results = search_web("rare topic")
    assert results == []