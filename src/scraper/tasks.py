import random
import requests
from celery import Celery
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.config import settings
from src.database.connection import SessionLocal
from src.database.models import ScrapedData, Source, ScrapedLog
from src.scraper.compliance import is_allowed
from src.scraper.parsers import parse_generic

app = Celery('scraper', broker=settings.REDIS_URL)

# --- HELPER: Database Logging ---
def log_event(db, level, message, task_id=None, url=None):
    try:
        log = ScrapedLog(
            level=level,
            message=str(message)[:500],
            task_id=task_id,
            url=url
        )
        db.add(log)
        db.commit()
    except Exception as e:
        print(f"FAILED TO LOG TO DB: {e}")
        db.rollback()

# --- HELPER: Fetcher with Retries ---
USER_AGENTS = getattr(settings, 'USER_AGENTS', [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
])

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.RequestException)
)
def fetch_url(session, url):
    """
    Standard requests fetch, but 'magically' async thanks to Gevent.
    """
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    # Use the passed session for connection pooling
    response = session.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.text, response.url

# --- CORE LOGIC ---
# Note: No 'async def' needed. Gevent handles the concurrency.
@app.task(bind=True) 
def scrape_task(self, url):
    task_id = self.request.id
    print(f"👨‍🍳 Chef is starting: {url}")
    
    db = SessionLocal()

    try:
        # --- SOURCE REGISTRATION ---
        parsed = urlparse(url)
        domain = parsed.netloc
        
        source = db.query(Source).filter(Source.domain == domain).first()
        if not source:
            try:
                source = Source(
                    domain=domain,
                    robots_url=f"{parsed.scheme}://{domain}/robots.txt",
                    last_crawled=datetime.now(timezone.utc) # time fixed
                )
                db.add(source)
                db.commit()
                db.refresh(source)
            except IntegrityError:
                db.rollback()
                source = db.query(Source).filter(Source.domain == domain).first()
        
        if source:
            source.last_crawled = datetime.now(timezone.utc) # pyright: ignore
            db.commit()
        # ---------------------------

        # 1. Check Compliance
        if not is_allowed(url):
            msg = f"Blocked by robots.txt: {url}"
            print(f"⛔ {msg}")
            log_event(db, "WARN", msg, task_id, url)
            return "Blocked"

        # 2. Fetch Data (High Performance)
        try:
            # We create a Session for every task to reuse TCP connections if needed
            # (Though in single-url tasks, it mainly helps with cookie handling if we add it later)
            with requests.Session() as session:
                html_content, final_url = fetch_url(session, url)
                
        except Exception as fetch_err:
            msg = f"Network Error: {fetch_err}"
            log_event(db, "ERROR", msg, task_id, url)
            return "Failed"

        # 3. Parse Data
        soup = BeautifulSoup(html_content, 'html.parser')
        extracted_data = parse_generic(soup)
        
        rich_content = {
            "status": "success",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            **extracted_data
        }

        # 4. Save to Database (Upsert)
        existing_record = db.query(ScrapedData).filter(ScrapedData.url == url).first()
        source_id_val = source.id if source else None
        
        if existing_record:
            db.query(ScrapedData).filter(ScrapedData.url == url).update({
                "title": extracted_data.get('title', 'No Title'),
                "content": rich_content,
                "source_id": source_id_val
            })
            log_event(db, "INFO", f"Updated data for {domain}", task_id, url)
        else:
            new_data = ScrapedData(
                url=url,
                title=extracted_data.get('title', 'No Title'),
                content=rich_content,
                source_id=source_id_val
            )
            db.add(new_data)
            log_event(db, "INFO", f"Created new data for {domain}", task_id, url)
        
        db.commit()
        return "Success"

    except Exception as e:
        db.rollback()
        print(f"🔥 KITCHEN FIRE: {e}")
        log_event(db, "ERROR", f"Exception: {e}", task_id, url)
        return "Error"
    finally:
        db.close()