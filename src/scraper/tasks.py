import random
import requests
from celery import Celery
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
from src.database.models import ScrapedData, Source, ScrapedLog, ScheduledJob

from src.ai.client import Brain
from src.database.models import ScheduledJob

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
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    response = session.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.text, response.url

# --- HELPER: Analyzer with Retries ---
@retry(stop=stop_after_attempt(3), wait=wait_fixed(10)) # Wait 10s between tries
def safe_analyze(brain, text):
    try:
        return brain.analyze_article(text)
    except Exception:
        print("🧠 Brain is busy or timed out. Retrying...")
        raise # Tenacity catches this and retries
# --- CORE LOGIC ---
@app.task(bind=True) 
def scrape_task(self, url, job_id=None):
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
            return "Blocked"

        # 2. Fetch Data
        try:
            with requests.Session() as session:
                html_content, final_url = fetch_url(session, url)
        except Exception as fetch_err:
            msg = f"Network Error: {fetch_err}"
            log_event(db, "ERROR", msg, task_id, url)
            return "Failed"

        # 3. Parse Data
        extracted_data = parse_smart(html_content, final_url)
        
        # 🧠 AI ENRICHMENT
        if extracted_data.get('clean_text'):
            try:
                # We wrap the brain call in a loop that handles timeouts
                brain = Brain()
                ai_data = safe_analyze(brain, extracted_data['clean_text']) # type: ignore # New helper function
                
                if ai_data:
                    extracted_data['ai_tags'] = ai_data.get('tags')
                    extracted_data['ai_category'] = ai_data.get('category')
                    extracted_data['ai_urgency'] = ai_data.get('urgency')
                    
                    # --- 🛡️ FIX: SANITIZE SUMMARY ---
                    raw_summary = ai_data.get('summary')
                    if raw_summary:
                        if isinstance(raw_summary, dict):
                            # If AI gives {"point1": "...", "point2": "..."}, join values into one string
                            extracted_data['summary'] = " ".join([str(v) for v in raw_summary.values()])
                        elif isinstance(raw_summary, list):
                            # If AI gives ["Sentence 1", "Sentence 2"], join them
                            extracted_data['summary'] = " ".join([str(s) for s in raw_summary])
                        else:
                            # Otherwise, just use it as string
                            extracted_data['summary'] = str(raw_summary)
                    # --------------------------------
            except Exception as e:
                print(f"🧠 Brain skipped: {e}")
        
        rich_content = {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "raw_metadata": extracted_data 
        }

        # 4. Save to Database
        existing_record = db.query(ScrapedData).filter(ScrapedData.url == url).first()
        source_id_val = source.id if source else None
        
        update_data = {
            "ai_tags": extracted_data.get('ai_tags'),
            "ai_category": extracted_data.get('ai_category'),
            "ai_urgency": extracted_data.get('ai_urgency'),
            "title": extracted_data.get('title'),
            "author": extracted_data.get('author'),
            "published_date": extracted_data.get('published_date'),
            "summary": extracted_data.get('summary'),
            "main_image": extracted_data.get('main_image'),
            "clean_text": extracted_data.get('clean_text'),
            "content": rich_content,
            "source_id": source_id_val
        }

        if existing_record:
            for key, value in update_data.items():
                setattr(existing_record, key, value)
            log_event(db, "INFO", f"Updated rich data for {domain}", task_id, url)
        else:
            new_data = ScrapedData(url=url, **update_data)
            db.add(new_data)
            log_event(db, "INFO", f"Created rich data for {domain}", task_id, url)
        
        db.commit()

        # 🤖 ADAPTIVE SCHEDULING (Updates interval based on urgency)
        if job_id and extracted_data.get('ai_urgency'):
            try:
                # Use a fresh session for the job update to ensure clean state
                # (Or strictly reuse db if attached, but re-query is safer here)
                job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
                if job:
                    adjust_schedule(db, job, extracted_data['ai_urgency'], has_new_content=True)
            except Exception as e:
                print(f"⚠️ Scheduler Adjust Failed: {e}")
        
        return "Success"

    except Exception as e:
        db.rollback()
        print(f"🔥 KITCHEN FIRE: {e}")
        log_event(db, "ERROR", f"Exception: {e}", task_id, url)
        return "Error"
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
                last_run = job.last_triggered_at.replace(tzinfo=timezone.utc) if job.last_triggered_at.tzinfo is None else job.last_triggered_at
                delta = now - last_run
                if delta.total_seconds() >= job.interval_seconds:
                    should_run = True
            
            if should_run:
                print(f"✅ [BEAT] Triggering job: {job.name}")
                scrape_task.delay(job.url, job_id=job.id)  # type: ignore
                job.last_triggered_at = now # type: ignore
                tasks_dispatched += 1
        
        if tasks_dispatched > 0:
            db.commit()
            return f"Dispatched {tasks_dispatched} tasks."
        return "No tasks due."

    except Exception as e:
        db.rollback()
        print(f"❌ [BEAT] Error: {e}")
        return "Error"
    finally:
        db.close()

# --- NEW HELPER FUNCTION (Was missing!) ---
def adjust_schedule(db, job, urgency, has_new_content):
    """
    Adjusts the interval_seconds based on AI urgency.
    """
    current_interval = job.interval_seconds
    
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
