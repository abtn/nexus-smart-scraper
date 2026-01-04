import random
import requests
from celery import Celery, chain
from celery.schedules import crontab
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from datetime import datetime, timezone
from sqlalchemy.exc import IntegrityError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, wait_fixed

from src.config import settings
from src.scraper.compliance import is_allowed
from src.scraper.parsers import parse_smart
from src.database.connection import SessionLocal
from src.database.models import ScrapedData, Source, ScrapedLog, ScheduledJob, AIStatus

from src.ai.client import Brain
from src.scraper.discovery import SitemapDiscovery # <--- NEW

app = Celery('scraper', broker=settings.REDIS_URL)

# --- ROUTING CONFIGURATION ---
# This ensures Fast logic goes to 'default' and Slow logic goes to 'ai_queue'
app.conf.task_routes = {
    'src.scraper.tasks.scrape_task': {'queue': 'default'},
    'src.scraper.tasks.enrich_task': {'queue': 'ai_queue'},
}

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
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    response = session.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.text, response.url

# --- HELPER: Analyzer with Retries ---
@retry(stop=stop_after_attempt(3), wait=wait_fixed(10)) 
def safe_analyze(brain, text):
    try:
        return brain.analyze_article(text)
    except Exception:
        print("🧠 Brain is busy or timed out. Retrying...")
        raise 

# ==========================================
# TASK 1: THE FAST SCRAPER (Ingestion)
# ==========================================
@app.task(bind=True, queue='default') 
def scrape_task(self, url, job_id=None):
    """
    Responsibilities:
    1. Robots.txt check
    2. Fetch HTML
    3. Parse Clean Text
    4. Save to DB with status='pending'
    5. Return ID for the next task
    """
    task_id = self.request.id
    print(f"👨‍🍳 Chef (Fast Worker) started: {url}")
    
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
                    last_crawled=datetime.now(timezone.utc)
                )
                db.add(source)
                db.commit()
                db.refresh(source)
            except IntegrityError:
                db.rollback()
                source = db.query(Source).filter(Source.domain == domain).first()
        
        if source:
            source.last_crawled = datetime.now(timezone.utc) # type: ignore
            db.commit()

        # 1. Check Compliance
        if not is_allowed(url):
            msg = f"Blocked by robots.txt: {url}"
            print(f"⛔ {msg}")
            log_event(db, "WARN", msg, task_id, url)
            return None # Stop chain

        # 2. Fetch Data
        try:
            with requests.Session() as session:
                html_content, final_url = fetch_url(session, url)
        except Exception as fetch_err:
            msg = f"Network Error: {fetch_err}"
            log_event(db, "ERROR", msg, task_id, url)
            return None # Stop chain

        # 3. Parse Data (No AI here!)
        extracted_data = parse_smart(html_content, final_url)
        
        rich_content = {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "raw_metadata": extracted_data 
        }

        # 4. Save to Database
        existing_record = db.query(ScrapedData).filter(ScrapedData.url == url).first()
        source_id_val = source.id if source else None
        
        # Prepare basic data
        update_data = {
            "title": extracted_data.get('title'),
            "author": extracted_data.get('author'),
            "published_date": extracted_data.get('published_date'),
            "main_image": extracted_data.get('main_image'),
            "clean_text": extracted_data.get('clean_text'),
            "summary": extracted_data.get('summary'), # This is the basic Trafilatura summary
            "content": rich_content,
            "source_id": source_id_val,
            
            # KEY CHANGE: Reset status to PENDING so AI picks it up
            "ai_status": AIStatus.PENDING,
            "ai_error_log": None 
        }

        row_id = None

        if existing_record:
            for key, value in update_data.items():
                setattr(existing_record, key, value)
            db.commit()
            row_id = existing_record.id
            log_event(db, "INFO", f"Updated basic data for {domain}", task_id, url)
        else:
            new_data = ScrapedData(url=url, **update_data)
            db.add(new_data)
            db.commit()
            db.refresh(new_data) # Important to get the ID
            row_id = new_data.id
            log_event(db, "INFO", f"Created basic data for {domain}", task_id, url)
        
        # RETURN ID so the next task (enrich_task) knows what to process
        return row_id

    except Exception as e:
        db.rollback()
        print(f"🔥 KITCHEN FIRE: {e}")
        log_event(db, "ERROR", f"Exception: {e}", task_id, url)
        return None
    finally:
        db.close()

# ==========================================
# TASK 2: THE SLOW ENRICHER (AI Brain)
# ==========================================
@app.task(bind=True, queue='ai_queue')
def enrich_task(self, article_id, job_id=None): # <--- Added job_id=None
    """
    Responsibilities:
    1. Load text from DB
    2. Call Ollama (Slow)
    3. Update DB with tags/category/urgency
    4. Set status='completed'
    5. Adjust Scheduler
    """
    if not article_id:
        return "Skipped (No ID)"
        
    db = SessionLocal()
    print(f"🧠 Brain (AI Worker) analyzing Article ID: {article_id}")

    try:
        article = db.query(ScrapedData).filter(ScrapedData.id == article_id).first()
        if not article:
            return "Article not found"

        # Idempotency: If it's already done, don't waste GPU cycles
        if article.ai_status == AIStatus.COMPLETED: # pyright: ignore[reportGeneralTypeIssues]
            return "Already Completed"

        # Update status to processing
        article.ai_status = AIStatus.PROCESSING # pyright: ignore[reportAttributeAccessIssue]
        db.commit()

        # Call the Brain
        brain = Brain()
        # safe_analyze handles retries
        ai_data = safe_analyze(brain, article.clean_text)

        if ai_data:
            article.ai_tags = ai_data.get('tags')
            article.ai_category = ai_data.get('category')
            article.ai_urgency = ai_data.get('urgency')
            
            # Sanitize summary
            raw_summary = ai_data.get('summary')
            if raw_summary:
                if isinstance(raw_summary, dict):
                    article.summary = " ".join([str(v) for v in raw_summary.values()]) # pyright: ignore[reportAttributeAccessIssue]
                elif isinstance(raw_summary, list):
                    article.summary = " ".join([str(s) for s in raw_summary]) # pyright: ignore[reportAttributeAccessIssue]
                else:
                    article.summary = str(raw_summary) # pyright: ignore[reportAttributeAccessIssue]

            article.ai_status = AIStatus.COMPLETED # pyright: ignore[reportAttributeAccessIssue]
            article.ai_error_log = None # pyright: ignore[reportAttributeAccessIssue]
            
            # 🤖 ADAPTIVE SCHEDULING (Moved here because we need Urgency)
            if job_id and article.ai_urgency:
                try:
                    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
                    if job:
                        adjust_schedule(db, job, article.ai_urgency, has_new_content=True)
                except Exception as e:
                    print(f"⚠️ Scheduler Adjust Failed: {e}")

        else:
            article.ai_status = AIStatus.FAILED # pyright: ignore[reportAttributeAccessIssue]
            article.ai_error_log = "AI returned no data (Model might be hallucinating empty JSON)" # pyright: ignore[reportAttributeAccessIssue]

        db.commit()
        return "Enrichment Success"

    except Exception as e:
        db.rollback()
        print(f"🧠 Brain Error: {e}")
        try:
            # Re-query in case session is dirty, to save the error
            err_article = db.query(ScrapedData).filter(ScrapedData.id == article_id).first()
            if err_article:
                err_article.ai_status = AIStatus.FAILED # pyright: ignore[reportAttributeAccessIssue]
                err_article.ai_error_log = str(e) # pyright: ignore[reportAttributeAccessIssue]
                db.commit()
        except:
            pass
        return f"Enrichment Error: {e}"
    finally:
        db.close()

# ==========================================
# TASK 3: THE CRAWLER (Discovery)
# ==========================================
@app.task(bind=True, queue='default')
def discover_sitemap_task(self, source_id: int, limit: int = 50):
    """
    1. Load Source
    2. Run SitemapDiscovery Strategy
    3. Queue new URLs for scraping
    """
    # Import locally to avoid circular dependencies
    from src.scraper.tasks import scrape_task, enrich_task
    # Import Discovery
    from src.scraper.discovery import SitemapDiscovery 
    
    task_id = self.request.id
    db = SessionLocal()
    
    try:
        source = db.query(Source).filter(Source.id == source_id).first()
        if not source:
            print(f"❌ Discovery Error: Source ID {source_id} not found.")
            return "Source Not Found"

        print(f"🕷️ Discovery Task started for: {source.domain}")
        
        # Run the discovery logic
        discovery = SitemapDiscovery(source.domain, db, limit=limit) # pyright: ignore[reportArgumentType]
        new_urls = discovery.run()
        
        if not new_urls:
            print(f"🕸️ No new URLs found for {source.domain}")
            return "No new URLs"

        print(f"🚀 Queuing {len(new_urls)} new articles for ingestion...")
        
        # Batch Dispatch
        # We dispatch tasks individually. The 'default' queue (gevent) handles this easily.
        count = 0
        for url in new_urls:
            try:
                # IMPORTANT: We trigger the CHAIN here (Scrape -> Enrich)
                # Just like the dashboard does.
                chain(
                    scrape_task.s(url),  # pyright: ignore[reportFunctionMemberAccess]
                    enrich_task.s() # pyright: ignore[reportFunctionMemberAccess]
                ).apply_async()
                
                count += 1
            except Exception as e:
                print(f"⚠️ Failed to queue URL {url}: {e}")
        
        # Update Source timestamp
        source.last_crawled = datetime.now(timezone.utc) # pyright: ignore[reportAttributeAccessIssue]
        db.commit()
        
        return f"Discovered & Queued {count} URLs"

    except Exception as e:
        db.rollback()
        print(f"🔥 Discovery Fire: {e}")
        return f"Discovery Error: {e}"
    finally:
        db.close()

# --- SCHEDULER LOGIC ---
@app.task
def periodic_check_task():
    print("⏰ [BEAT] Checking database for active schedules...")
    db = SessionLocal()
    try:
        active_jobs = db.query(ScheduledJob).filter(ScheduledJob.is_active == True).all()
        now = datetime.now(timezone.utc)
        tasks_dispatched = 0
        
        for job in active_jobs:
            should_run = False
            if job.last_triggered_at is None:
                should_run = True 
            else:
                # Ensure timezone awareness
                last_run = job.last_triggered_at.replace(tzinfo=timezone.utc) if job.last_triggered_at.tzinfo is None else job.last_triggered_at
                delta = now - last_run
                if delta.total_seconds() >= job.interval_seconds:
                    should_run = True
            
            if should_run:
                print(f"✅ [BEAT] Triggering chain for job: {job.name}")
                
                # --- THE CHAIN ---
                # 1. Scrape (Fast): Returns article_id
                # 2. Enrich (Slow): Receives article_id as 1st arg, and job_id as kwarg
                workflow = chain(
                    scrape_task.s(job.url, job_id=job.id), # pyright: ignore[reportFunctionMemberAccess]
                    enrich_task.s(job_id=job.id)  # pyright: ignore[reportFunctionMemberAccess]
                )
                workflow.apply_async()
                # -----------------

                job.last_triggered_at = now # pyright: ignore[reportAttributeAccessIssue]
                tasks_dispatched += 1
        
        if tasks_dispatched > 0:
            db.commit()
            return f"Dispatched {tasks_dispatched} chains."
        return "No tasks due."

    except Exception as e:
        db.rollback()
        print(f"❌ [BEAT] Error: {e}")
        return "Error"
    finally:
        db.close()
        
# --- HELPER FUNCTION (Scheduler) ---
def adjust_schedule(db, job, urgency, has_new_content):
    """
    Adjusts the interval_seconds based on AI urgency.
    """
    current_interval = job.interval_seconds

    # 1. FAST PATH: Python Logic (Deterministic & Safe)
    if has_new_content:
        if urgency >= 8:
            # Breaking news: Check every 5 minutes
            new_interval = 300 
        elif urgency >= 5:
            # Important: Check every 30 mins
            new_interval = 1800
        else:
            # Evergreen: Default to 1 hour, or slow down slightly
            new_interval = max(3600, int(current_interval * 0.95))
    else:
        # No content: Back off exponentially
        new_interval = min(86400, int(current_interval * 1.5))

    # 2. SMART PATH (Future Feature): Local LLM Decision
    # Uncomment this block when you want to enable "Deep Thinking" scheduling
    """
    try:
        from src.ai.client import Brain
        brain = Brain()
        prompt = f"Job: {job.name}, Urgency: {urgency}/10. Current interval: {current_interval}s. Suggest new interval in seconds (int only)."
        # We use think_schedule (Local LLM) to save API credits
        decision = brain.think_schedule(prompt)
        if decision:
            # Simple cleanup to find numbers in response
            import re
            numbers = re.findall(r'\d+', decision)
            if numbers:
                suggested = int(numbers[0])
                # Sanity check: don't go below 1 min or above 2 days
                if 60 <= suggested <= 172800:
                    new_interval = suggested
    except Exception as e:
        print(f"⚠️ Smart Scheduler Error: {e}")
    """
        
    job.interval_seconds = int(new_interval)
    print(f"⚖️ Adaptive Scheduler: '{job.name}' urgency={urgency} -> interval={new_interval}s")
    db.commit()

# --- CONFIG ---
app.conf.beat_schedule = {
    'dynamic-dispatcher': {
        'task': 'src.scraper.tasks.periodic_check_task',
        'schedule': 60.0,
    },
}