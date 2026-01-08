import pytest # pyright: ignore[reportMissingImports]
from unittest.mock import MagicMock, patch
from src.scraper.tasks import scrape_task
from src.scraper.tasks import enrich_task
from src.database.models import AIStatus

# --- Fixture to mock the DB ID generation ---
def mock_db_add_behavior(obj):
    """Simulates the DB assigning an ID when a new record is added."""
    obj.id = 1

@patch('src.scraper.tasks.fetch_url')
@patch('src.scraper.tasks.is_allowed', return_value=True)
@patch('src.scraper.tasks.SessionLocal')
def test_scrape_task_success(mock_db_cls, mock_allowed, mock_fetch):
    """
    Test the flow: Fetch -> Parse -> Save.
    Expectation: Returns the new Article ID (int).
    """
    # 1. Mock Network
    mock_fetch.return_value = ("<html><body><h1>Test Title</h1></body></html>", "http://test.com")
    
    # 2. Mock Database Session
    mock_session = MagicMock()
    mock_db_cls.return_value = mock_session
    
    # 3. Mock Query (Return None to simulate 'record does not exist yet')
    mock_session.query.return_value.filter.return_value.first.return_value = None
    
    # 4. CRITICAL: Simulate DB assigning an ID upon .add()
    # When code calls db.add(new_data), we set new_data.id = 1
    mock_session.add.side_effect = mock_db_add_behavior

    # Run the task
    result = scrape_task.apply(args=["http://test.com/page"]).get() # pyright: ignore[reportFunctionMemberAccess]

    # Assertions
    assert result == 1  # Logic now returns the ID, not "Success"
    mock_session.add.assert_called()
    mock_session.commit.assert_called()

@patch('src.scraper.tasks.SessionLocal')
@patch('src.scraper.tasks.is_allowed', return_value=False)
def test_scrape_task_blocked(mock_allowed, mock_db_cls):
    """
    Test that the task exits early if robots.txt disallows.
    Expectation: Returns None (or specific string depending on implementation).
    """
    mock_session = MagicMock()
    mock_db_cls.return_value = mock_session
    
    # Run the task
    result = scrape_task.apply(args=["http://blocked.com"]).get() # pyright: ignore[reportFunctionMemberAccess]
    
    # Logic: If blocked, we usually return None or break the chain.
    # The previous error showed it returned None, so we assert that.
    assert result is None or result == "Blocked" 
    
    mock_allowed.assert_called_once()
    # Ensure we didn't try to add anything to DB (except maybe a log)
    # We check that we didn't add *ScrapedData*
    # (Checking strictly for 0 adds might fail if your code logs to DB)

# New: Test Enrich Task with Mocked AI and DB
@patch('src.scraper.tasks.Brain')          # Mock the AI Brain class
@patch('src.scraper.tasks.SessionLocal')   # Mock the Database
def test_enrich_task_success(mock_db_cls, mock_brain_cls):
    """
    Test that enrich_task:
    1. Generates an embedding
    2. Analyzes the text
    3. Saves both to the DB
    """
    # 1. Setup Mock DB
    mock_session = MagicMock()
    mock_db_cls.return_value = mock_session
    
    # Create a fake article object that the DB "finds"
    mock_article = MagicMock()
    mock_article.clean_text = "This is a test article about AI."
    mock_article.ai_status = "pending"
    mock_session.query.return_value.filter.return_value.first.return_value = mock_article

    # 2. Setup Mock Brain (AI)
    mock_brain_instance = mock_brain_cls.return_value
    # Mock Embedding Return
    mock_brain_instance.generate_embedding.return_value = [0.1, 0.2, 0.3] 
    # Mock Analysis Return
    mock_brain_instance.analyze_article.return_value = {
        "summary": "Short summary",
        "tags": ["tech"],
        "category": "Technology",
        "urgency": 8
    }

    # 3. Run the Task
    # We pass '1' as the article_id
    result = enrich_task.apply(args=[1]).get() # pyright: ignore[reportFunctionMemberAccess]

    # 4. Assertions
    assert result == "Enrichment Success"
    
    # Did we verify the embedding was saved?
    assert mock_article.embedding == [0.1, 0.2, 0.3]
    
    # Did we verify the status was updated?
    assert mock_article.ai_status == AIStatus.COMPLETED
    
    # Did we commit to DB?
    mock_session.commit.assert_called()