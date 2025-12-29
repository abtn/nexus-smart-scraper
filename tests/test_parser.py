from unittest.mock import patch
from src.scraper.parsers import parse_smart

def test_parse_smart_valid_json(mocker):
    """
    Test that parse_smart correctly parses the JSON output from trafilatura.
    """
    # We mock 'trafilatura.extract' to return a specific JSON string.
    # This keeps the test fast and independent of external library logic.
    mock_extract = mocker.patch('src.scraper.parsers.trafilatura.extract')
    
    # Simulate a successful trafilatura response
    mock_extract.return_value = '{"title": "Test Article", "author": "John Doe", "text": "Body text here"}'

    html_content = "<html><body>...</body></html>"
    url = "http://test.com"
    
    result = parse_smart(html_content, url)
    
    # Assertions
    assert result['title'] == "Test Article"
    assert result['author'] == "John Doe"
    assert result['clean_text'] == "Body text here"

def test_parse_smart_fallback_to_bs4(mocker):
    """
    Test that if trafilatura returns nothing, we fallback to BeautifulSoup for the title.
    """
    # Mock trafilatura to return None (simulating a parse failure)
    mocker.patch('src.scraper.parsers.trafilatura.extract', return_value=None)
    
    html_content = "<html><head><title>Fallback Title</title></head><body></body></html>"
    url = "http://test.com"
    
    result = parse_smart(html_content, url)
    
    # Should use BeautifulSoup fallback
    assert result['title'] == "Fallback Title"
    # Other fields should be None because trafilatura failed
    assert result['clean_text'] is None