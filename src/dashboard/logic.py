import re
import pandas as pd
import ast
from sqlalchemy import create_engine
from datetime import datetime
from urllib.parse import urlparse
from celery import chain

from src.config import settings
from src.database.connection import SessionLocal
from src.database.models import ScrapedData, ScheduledJob, Source, JobType
from src.scraper.tasks import process_rss_task, discover_sitemap_task, scrape_task, enrich_task

from src.scraper.hunter import search_web # import the web search function

# --- 1. DATA FETCHING ---
def get_engine():
    return create_engine(settings.DB_URL)

def load_analytics_data():
    """Fetches articles and cleans them for the UI."""
    engine = get_engine()
    try:
        query = """
            SELECT id, url, title, created_at,
                   ai_category, ai_urgency, ai_tags,
                   summary, ai_status, ai_error_log,
                   source_id
            FROM scraped_data
            ORDER BY created_at DESC
            LIMIT 200
        """
        df = pd.read_sql(query, engine)

        if df.empty: return pd.DataFrame()

        # Clean Tags (String -> List)
        def parse_tags(tag_str):
            if not tag_str: return []
            try: return ast.literal_eval(tag_str) if isinstance(tag_str, str) else tag_str
            except: return []

        df['ai_tags'] = df['ai_tags'].apply(parse_tags)
        # Ensure numeric urgency
        df['ai_urgency'] = pd.to_numeric(df['ai_urgency'], errors='coerce').fillna(0)
        # Ensure datetime
        df['created_at'] = pd.to_datetime(df['created_at'])
        
        return df
    except Exception as e:
        print(f"Error loading data: {e}")
        return pd.DataFrame()

def get_active_jobs():
    """Fetches jobs for the sidebar list."""
    db = SessionLocal()
    try:
        jobs = db.query(ScheduledJob).order_by(ScheduledJob.created_at.desc()).all()
        return jobs
    finally:
        db.close()

# --- 2. SMART LOGIC ---
def detect_source_type(url: str):
    """
    Analyzes a URL and suggests the Job Type and Interval.
    Returns: (JobType, interval, label_text)
    """
    url_lower = url.lower().strip()
    
    # RSS Detection
    if any(x in url_lower for x in ['.xml', '.rss', '/feed', 'feeds.']):
        return JobType.RSS, 600, "RSS Feed"
    
    # Single Article Detection (Date patterns or deep IDs)
    if re.search(r'/\d{4}/\d{2}/', url_lower) or re.search(r'[-/]\d{6,}', url_lower):
        return JobType.SINGLE, 0, "Single Article"

    # Default: Discovery
    return JobType.DISCOVERY, 3600, "Site Discovery"

def create_and_trigger_job(url: str, name: str = None, force_single: bool = False): # pyright: ignore[reportArgumentType] # <--- Added argument
    """
    The 'Magic' function. Detects type, saves DB, triggers Celery.
    """
    db = SessionLocal()
    try:
        # 1. Detect Strategy
        if force_single:
            # Override detection if user checked the box
            j_type = JobType.SINGLE
            interval = 0
            label = "Single Article"
        else:
            # Use Auto-Detection
            j_type, interval, label = detect_source_type(url)
        
        # 2. Name generation if empty
        if not name:
            parsed = urlparse(url)
            name = f"{label}: {parsed.netloc}"

        # 3. Create Job
        job = ScheduledJob(
            name=name,
            url=url,
            interval_seconds=interval,
            items_limit=10 if j_type != JobType.SINGLE else 1,
            is_active=True,
            job_type=j_type
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        # 4. Immediate Trigger (Kickstart)
        if j_type == JobType.RSS:
            process_rss_task.apply_async(args=[job.url, job.id, job.items_limit]) # pyright: ignore[reportFunctionMemberAccess]
        
        elif j_type == JobType.DISCOVERY:
            # Auto-create source if needed
            domain = urlparse(url).netloc
            src = db.query(Source).filter(Source.domain == domain).first()
            if not src:
                src = Source(domain=domain, robots_url=f"https://{domain}/robots.txt")
                db.add(src)
                db.commit()
            discover_sitemap_task.apply_async(args=[src.id, job.items_limit, False, job.id]) # pyright: ignore[reportFunctionMemberAccess]

        else: # Single
            chain(scrape_task.s(job.url, job_id=job.id), enrich_task.s(job_id=job.id)).apply_async() # pyright: ignore[reportFunctionMemberAccess]

        return True, f"Created & Started {label}"

    except Exception as e:
        return False, str(e)
    finally:
        db.close()

def delete_job(job_id: int):
    db = SessionLocal()
    try:
        db.query(ScheduledJob).filter(ScheduledJob.id == job_id).delete()
        db.commit()
    finally:
        db.close()

def clear_failed_tasks():
    """Deletes articles that failed AI processing."""
    db = SessionLocal()
    try:
        rows_deleted = db.query(ScrapedData).filter(ScrapedData.ai_status == 'failed').delete()
        db.commit()
        return True, f"Cleared {rows_deleted} failed tasks."
    except Exception as e:
        db.rollback()
        return False, f"Error: {e}"
    finally:
        db.close()
        
# --- 3. HUNTER WRAPPER ---
def hunt_topic(topic: str, limit: int = 10):
    """
    Wrapper for the Hunter to be used in the Dashboard.
    Returns: (SuccessBool, MessageString, URLList)
    """
    try:
        urls = search_web(topic, max_results=limit)
        if not urls:
            return False, "No valid sources found.", []
        
        return True, f"Found {len(urls)} new sources.", urls
    except Exception as e:
        return False, str(e), []