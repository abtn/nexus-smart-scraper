from pydantic import BaseModel, ConfigDict, Field # import ConfigDict for ORM mode support
from datetime import datetime
from typing import Optional, List # import Optional for optional fields

class ArticleResponse(BaseModel):
    # Basic article information - used in lists
    id: int
    url: str
    title: Optional[str] = None
    author: Optional[str] = None
    published_date: Optional[str] = None
    summary: Optional[str] = None
    main_image: Optional[str] = None
    created_at: datetime

    # Config to allow reading from SQLAlchemy models (ORM mode)
    model_config = ConfigDict(from_attributes=True)

class ArticleDetail(ArticleResponse):
    """Includes the full text - used when clicking into an article"""
    clean_text: Optional[str] = None

# --- NEW: GENERATION SCHEMAS ---
class GenerateRequest(BaseModel):
    prompt: str = Field(..., description="Topic or question to answer")
    max_new_sources: int = Field(3, ge=1, le=10, description="Max new URLs to scrape if knowledge is low")

class GenerateResponse(BaseModel):
    task_id: str
    status: str
    message: str

class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: Optional[str] = None
    generated_text: Optional[str] = None
    articles_used: int = 0
    created_at: datetime