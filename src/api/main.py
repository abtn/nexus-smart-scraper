from fastapi import FastAPI, Depends, HTTPException, Query # type: ignore # import FastAPI and other dependencies
from fastapi.middleware.cors import CORSMiddleware # type: ignore
from sqlalchemy import or_ # import or_ for complex queries
from sqlalchemy.orm import Session # import Session for database interactions
from typing import List # import List for type hinting

from src.database.connection import get_db # import the database session dependency
from src.database.models import ScrapedData, GeneratedContent, GeneratedContentStatus # import the database models
from src.api.schemas import ArticleResponse, ArticleDetail, GenerateRequest, GenerateResponse, TaskStatusResponse
 # import the response schemas

from src.ai.memory import search_memory # import the memory search function
from src.scraper.hunter import search_web # import the web search function
from src.scraper.tasks import generate_content_task
import uuid

app = FastAPI(title="Scraper API", version="1.0.0") # Initialize FastAPI app

# --- CORS SETTINGS ---
# This allows Next.js apps (running on different ports/domains) to hit this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, replace "*" with specific domains ["https://cryptodaily.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "message": "Scraper API is running"}
# 1. Get List of Articles
@app.get("/api/v1/articles", response_model=List[ArticleResponse])
def get_articles(
    skip: int = 0, 
    limit: int = 20, 
    q: str = Query(None, description="Search term for title or summary"),
    db: Session = Depends(get_db)
):
    """
    Fetch a list of articles with optional search filtering.
    """
    # 1. Start with the base query
    query = db.query(ScrapedData)
    
    # 2. Apply Search Filter (THIS WAS MISSING OR BROKEN)
    if q:
        search_fmt = f"%{q}%" # Create a pattern like %python%
        query = query.filter(
            or_(
                ScrapedData.title.ilike(search_fmt),   # Case-insensitive search in Title
                ScrapedData.summary.ilike(search_fmt)  # Case-insensitive search in Summary
            )
        )
    
    # 3. Apply Sorting and Pagination
    articles = query.order_by(ScrapedData.created_at.desc())\
                    .offset(skip)\
                    .limit(limit)\
                    .all()
    
    return articles
# ------------------------------
# 2. Get Single Article (With Full Text)
@app.get("/api/v1/articles/{article_id}", response_model=ArticleDetail)
def get_article_detail(article_id: int, db: Session = Depends(get_db)):
    """
    Fetch full details of a specific article including clean_text.
    """
    article = db.query(ScrapedData).filter(ScrapedData.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article

# New: Semantic Memory Search Endpoint
@app.get("/api/v1/memory/search")
def search_memory_api(
    q: str = Query(..., description="Search query"),
    limit: int = 5
):
    """
    Semantic Search: Finds articles based on meaning, not just keywords.
    """
    results = search_memory(q, limit=limit)
    return {
        "query": q,
        "count": len(results),
        "results": [
            {
                "id": r.id,
                "title": r.title,
                "category": r.ai_category,
                "similarity_score": "N/A" # Complexity omitted for brevity
            } for r in results
        ]
    }

# Hunt Endpoint to Search the Web
@app.post("/api/v1/hunt")
def hunt_for_sources(
    topic: str = Query(..., description="Topic to search for"),
    limit: int = Query(10, description="Max number of results")
):
    """
    The 'Eyes' of Nexus.
    Searches the web for relevant URLs based on a topic.
    """
    try:
        urls = search_web(topic, max_results=limit)
        return {
            "topic": topic,
            "found_count": len(urls),
            "targets": urls
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- NEW: GENERATION ENDPOINTS ---
@app.post("/api/generate", response_model=GenerateResponse)
def start_generation(request: GenerateRequest):
    """
    Starts the Adaptive Intelligence Workflow.
    """
    task_id = f"gen_{uuid.uuid4().hex[:12]}"
    
    db = next(get_db())
    try:
        new_task = GeneratedContent(
            task_id=task_id,
            user_prompt=request.prompt,
            status=GeneratedContentStatus.PROCESSING
        )
        db.add(new_task)
        db.commit()
    finally:
        db.close()
        
    # Trigger Celery Task
    generate_content_task.apply_async( # pyright: ignore[reportFunctionMemberAccess]
        args=[task_id, request.prompt, request.max_new_sources],
        task_id=task_id
    )
    
    return GenerateResponse(
        task_id=task_id,
        status="processing",
        message="Workflow started."
    )

@app.get("/api/generate/{task_id}", response_model=TaskStatusResponse)
def get_generation_status(task_id: str):
    """Check the status of a generation task"""
    db = next(get_db())
    try:
        task = db.query(GeneratedContent).filter(GeneratedContent.task_id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # FIX: task.status is a String, not an Enum object. 
        # We compare it directly to the Enum's value string.
        progress_msg = task.status
        
        if task.status == GeneratedContentStatus.PROCESSING.value: # type: ignore # Compare string to string
            if task.search_queries: # type: ignore
                progress_msg = "Hunting for new data..."
            else:
                progress_msg = "Analyzing & Synthesizing..."

        return TaskStatusResponse(
            task_id=task.task_id, # pyright: ignore[reportArgumentType]
            status=task.status, # FIX: Remove .value here # pyright: ignore[reportArgumentType]
            progress=progress_msg, # pyright: ignore[reportArgumentType]
            generated_text=task.generated_text, # pyright: ignore[reportArgumentType]
            articles_used=len(task.used_article_ids) if task.used_article_ids else 0, # type: ignore
            created_at=task.created_at # pyright: ignore[reportArgumentType]
        )
    finally:
        db.close()