import random
import requests
import trafilatura.sitemaps # pyright: ignore[reportMissingImports] # <--- Added for parsing XML
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
from src.database.models import ScrapedData, Source, ScrapedLog, ScheduledJob, AIStatus, GeneratedContent

from src.ai.client import Brain
# Import the prioritization helper we made
from src.scraper.discovery import fetch_sitemaps, crawl_recursive

import feedparser # pyright: ignore[reportMissingImports] 
from src.database.models import JobType # <--- NEW

app = Celery('scraper', broker=settings.REDIS_URL)

# --- ROUTING CONFIGURATION ---
app.conf.task_routes = {
    'src.scraper.tasks.scrape_task': {'queue': 'default'},
    'src.scraper.tasks.enrich_task': {'queue': 'ai_queue'},
    'src.scraper.tasks.discover_sitemap_task': {'queue': 'default'}, # Discovery is fast I/O
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
            return None 

        # 2. Fetch Data
        try:
            with requests.Session() as session:
                html_content, final_url = fetch_url(session, url)
        except Exception as fetch_err:
            msg = f"Network Error: {fetch_err}"
            print(f"❌ {msg}")  # <--- ADD THIS LINE to see errors in logs
            log_event(db, "ERROR", msg, task_id, url)
            return None

        # 3. Parse Data
        extracted_data = parse_smart(html_content, final_url)
        
        rich_content = {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "raw_metadata": extracted_data 
        }

        # 4. Save to Database
        existing_record = db.query(ScrapedData).filter(ScrapedData.url == url).first()
        source_id_val = source.id if source else None
        
        update_data = {
            "title": extracted_data.get('title'),
            "author": extracted_data.get('author'),
            "published_date": extracted_data.get('published_date'),
            "main_image": extracted_data.get('main_image'),
            "clean_text": extracted_data.get('clean_text'),
            "summary": extracted_data.get('summary'),
            "content": rich_content,
            "source_id": source_id_val,
            "ai_status": AIStatus.PENDING, # Reset status
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
            db.refresh(new_data) 
            row_id = new_data.id
            log_event(db, "INFO", f"Created basic data for {domain}", task_id, url)
        
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
def enrich_task(self, article_id, job_id=None):
    if not article_id:
        return "Skipped (No ID)"
        
    db = SessionLocal()
    print(f"🧠 Brain (AI Worker) analyzing Article ID: {article_id}")

    try:
        article = db.query(ScrapedData).filter(ScrapedData.id == article_id).first()
        if not article:
            return "Article not found"

        if article.ai_status == AIStatus.COMPLETED: # pyright: ignore
            return "Already Completed"

        article.ai_status = AIStatus.PROCESSING # pyright: ignore
        db.commit()

        # Call the Brain
        brain = Brain()
        ai_data = safe_analyze(brain, article.clean_text)

        # 1. Generate Embeddings (NEW)
        # We do this independently of the analysis so we get vector data even if analysis fails
        vector = brain.generate_embedding(article.clean_text) # pyright: ignore[reportArgumentType]
        if vector:
            article.embedding = vector # pyright: ignore[reportAttributeAccessIssue]

        # 2. Analyze Content (Existing)
        ai_data = safe_analyze(brain, article.clean_text)
        
        if ai_data:
            article.ai_tags = ai_data.get('tags')
            article.ai_category = ai_data.get('category')
            article.ai_urgency = ai_data.get('urgency')
            
            raw_summary = ai_data.get('summary')
            if raw_summary:
                if isinstance(raw_summary, dict):
                    article.summary = " ".join([str(v) for v in raw_summary.values()]) # pyright: ignore
                elif isinstance(raw_summary, list):
                    article.summary = " ".join([str(s) for s in raw_summary]) # pyright: ignore
                else:
                    article.summary = str(raw_summary) # pyright: ignore

            article.ai_status = AIStatus.COMPLETED # pyright: ignore
            article.ai_error_log = None # pyright: ignore
            
            if job_id and article.ai_urgency:
                try:
                    job = db.query(ScheduledJob).filter(ScheduledJob.id == job_id).first()
                    if job:
                        adjust_schedule(db, job, article.ai_urgency, has_new_content=True)
                except Exception as e:
                    print(f"⚠️ Scheduler Adjust Failed: {e}")

        else:
            article.ai_status = AIStatus.FAILED # pyright: ignore
            article.ai_error_log = "AI returned no data" # pyright: ignore

        db.commit()
        return "Enrichment Success"

    except Exception as e:
        db.rollback()
        print(f"🧠 Brain Error: {e}")
        try:
            err_article = db.query(ScrapedData).filter(ScrapedData.id == article_id).first()
            if err_article:
                err_article.ai_status = AIStatus.FAILED # pyright: ignore
                err_article.ai_error_log = str(e) # pyright: ignore
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
def discover_sitemap_task(self, source_id: int, limit: int = 50, force_crawl: bool = False, job_id: int = None): # pyright: ignore[reportArgumentType]
    """
    1. Load Source
    2. IF force_crawl is True -> Run Recursive Crawler
    3. ELSE -> Try Sitemaps -> Fallback to Recursive Crawler
    4. Queue new URLs via Chain
    """
    task_id = self.request.id
    db = SessionLocal()

    try:
        source = db.query(Source).filter(Source.id == source_id).first()
        if not source:
            print(f"❌ Discovery Error: Source ID {source_id} not found.")
            return "Source Not Found"

        print(f"🕷️ Discovery Task started for: {source.domain} (Force Crawl: {force_crawl})")

        base_url = f"https://{source.domain}" if not source.domain.startswith('http') else source.domain # pyright: ignore[reportGeneralTypeIssues]
        discovered_urls = set()

        # --- STRATEGY: FORCE CRAWL ---
        if force_crawl:
            print("💪 Force Mode: Skipping sitemaps, launching Recursive Crawler.")
            discovered_urls = set(crawl_recursive(base_url, max_articles=limit, depth_limit=2))

        # --- STRATEGY: AUTO (SITEMAP -> FALLBACK) ---
        else:
            # 1. Try Sitemap
            sitemaps = fetch_sitemaps(base_url)
            
            if sitemaps:
                for sm_url in sitemaps:
                    if len(discovered_urls) >= limit:
                        break
                    print(f"📄 Parsing Sitemap: {sm_url}")
                    try:
                        links = trafilatura.sitemaps.sitemap_search(sm_url)
                        if links:
                            for link in links:
                                if len(discovered_urls) >= limit: break
                                discovered_urls.add(link)
                    except Exception as e:
                        print(f"⚠️ Sitemap parse error: {e}")

            # 2. Fallback to Recursive if empty
            if not discovered_urls:
                print(f"⚠️ No sitemap links found. Switching to Recursive Crawler...")
                discovered_urls = set(crawl_recursive(base_url, max_articles=limit, depth_limit=2))

        if not discovered_urls:
            return "No articles found via Sitemap or Crawler"

        print(f"🚀 Queuing {len(discovered_urls)} new articles...")

        # Batch Dispatch
        count = 0
        for url in discovered_urls:
            exists = db.query(ScrapedData).filter(ScrapedData.url == url).first()
            if not exists:
                try:
                    workflow = chain(
                        scrape_task.s(url), # pyright: ignore[reportFunctionMemberAccess]
                        enrich_task.s() # pyright: ignore[reportFunctionMemberAccess]
                    )
                    workflow.apply_async()
                    count += 1
                except Exception as e:
                    print(f"⚠️ Failed to queue URL {url}: {e}")

        source.last_crawled = datetime.now(timezone.utc) # pyright: ignore[reportAttributeAccessIssue]
        db.commit()

        return f"Discovered & Queued {count} URLs"

    except Exception as e:
        db.rollback()
        print(f"🔥 Discovery Fire: {e}")
        return f"Discovery Error: {e}"
    finally:
        db.close()
# ==========================================
# TASK 4: RSS READER
# ==========================================
@app.task(bind=True, queue='default')
def process_rss_task(self, rss_url, job_id=None, limit=10):
    """
    1. Parse RSS Feed
    2. Extract Links (Up to limit)
    3. Chain Scrape -> Enrich for new items
    """
    task_id = self.request.id
    db = SessionLocal()
    
    try:
        print(f"📡 RSS Task started for: {rss_url} (Limit: {limit})")
        
        # 1. Fetch Feed
        feed = feedparser.parse(rss_url)
        
        if feed.bozo: 
            print(f"⚠️ RSS Feed might be malformed: {feed.bozo}")

        count = 0
        
        # 2. Iterate Entries (Limited)
        for entry in feed.entries[:limit]:
            target_url = getattr(entry, 'link', None)
            if not target_url: continue
            
            # 3. Check DB
            exists = db.query(ScrapedData).filter(ScrapedData.url == target_url).first()
            
            if not exists:
                try:
                    # 4. Dispatch Chain
                    workflow = chain(
                        scrape_task.s(target_url, job_id=job_id), # pyright: ignore[reportFunctionMemberAccess]
                        enrich_task.s(job_id=job_id) # pyright: ignore[reportFunctionMemberAccess]
                    )
                    workflow.apply_async()
                    count += 1
                except Exception as e:
                    print(f"⚠️ Failed to queue RSS Item {target_url}: {e}")

        return f"RSS Check Complete. Queued {count} new items."

    except Exception as e:
        print(f"🔥 RSS Task Error: {e}")
        return "RSS Error"
    finally:
        db.close()
# --- SCHEDULER LOGIC ---
# ==========================================
# UPDATE: SCHEDULER LOGIC
# ==========================================
@app.task(queue='default')  # <--- Added queue='default'
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
                print(f"✅ [BEAT] Triggering {job.job_type.value} job: {job.name}")
                
                # --- DISPATCH STRATEGY ---
                if job.job_type == JobType.RSS: # pyright: ignore[reportGeneralTypeIssues]
                    process_rss_task.apply_async(args=[job.url, job.id]) # pyright: ignore[reportFunctionMemberAccess]
                    
                elif job.job_type == JobType.DISCOVERY: # pyright: ignore[reportGeneralTypeIssues]
                    # RESOLVE SOURCE ID FROM URL
                    domain = urlparse(job.url).netloc # pyright: ignore[reportCallIssue, reportArgumentType]
                    source = db.query(Source).filter(Source.domain == domain).first()
                    
                    if source:
                        # Pass job_id to the task now that we updated the signature
                        discover_sitemap_task.apply_async(args=[source.id, 50, False, job.id]) # pyright: ignore[reportFunctionMemberAccess]
                    else:
                        print(f"⚠️ Job {job.id} failed: No Source found for domain {domain}")
                        # Optional: Auto-create source here if you want to be very robust
                    
                else:
                    # Default: Single URL Scrape
                    workflow = chain(
                        scrape_task.s(job.url, job_id=job.id), # pyright: ignore[reportFunctionMemberAccess]
                        enrich_task.s(job_id=job.id) # pyright: ignore[reportFunctionMemberAccess]
                    )
                    workflow.apply_async()

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
    current_interval = job.interval_seconds
    if has_new_content:
        if urgency >= 8: new_interval = 300 
        elif urgency >= 5: new_interval = 1800
        else: new_interval = max(3600, int(current_interval * 0.95))
    else:
        new_interval = min(86400, int(current_interval * 1.5))
        
    job.interval_seconds = int(new_interval)
    print(f"⚖️ Adaptive Scheduler: '{job.name}' urgency={urgency} -> interval={new_interval}s")
    db.commit()

# --- CONFIG ---
app.conf.beat_schedule = {
    'dynamic-dispatcher': {
        'task': 'src.scraper.tasks.periodic_check_task',
        'schedule': 10.0,  # <--- CHANGED FROM 60.0 TO 10.0
    },
}
@app.task(bind=True, queue='ai_queue')
def generate_content_task(self, task_id: str, user_prompt: str, max_sources: int, model_id: str = None, use_judge: bool = False): # pyright: ignore[reportArgumentType]
    """
    Celery Wrapper for the Orchestrator workflow.
    """
    # Local import to prevent circular dependency
    from src.ai.orchestrator import Orchestrator
    
    print(f"🚀 [BRAIN] Starting workflow Task ID: {task_id}")
    orchestrator = Orchestrator(task_id)
    orchestrator.run(user_prompt, max_sources, model_id, use_judge)
    return "Workflow Finished"