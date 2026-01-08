from unittest.mock import patch, MagicMock
from src.scraper.hunter import search_web

@patch('src.scraper.hunter.DDGS') # Mock the Search Engine
@patch('src.scraper.hunter.is_allowed', return_value=True) # Mock Compliance
def test_search_web_success(mock_allowed, mock_ddgs_cls):
    """
    Test that search_web parses results and applies filters correctly.
    """
    # 1. Setup Mock DDGS
    mock_ddgs_instance = mock_ddgs_cls.return_value
    # Context manager support (__enter__)
    mock_ddgs_instance.__enter__.return_value = mock_ddgs_instance
    
    # Mock results: One good, one YouTube (should be filtered), one PDF (should be filtered)
    mock_ddgs_instance.text.return_value = [
        {"href": "https://valid.com/article", "title": "Good Article"},
        {"href": "https://youtube.com/watch?v=123", "title": "Video"},
        {"href": "https://valid.com/report.pdf", "title": "PDF Report"}
    ]

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