import requests 
from bs4 import BeautifulSoup  # type: ignore
from sqlalchemy.exc import IntegrityError  # type: ignore
from celery import Celery
from src.config import settings
from src.database.models import ScrapedData
from src.database.connection import SessionLocal
from src.scraper.compliance import is_allowed


app = Celery('scraper', broker=settings.REDIS_URL)
# Use aiohttp to fetch a simple page (e.g., https://example.com).

@app.task
def scrape_task(url):
    print(f"👨‍🍳 Chef is starting: {url}")

    # 1. Check Compliance
    if not is_allowed(url):
        print(f"⛔ STOP: Robots.txt forbids {url}")
        return "Blocked"

    try:
        # 2. Fetch the Data (Download HTML)
        # We use a fake user-agent so we don't look like a robot
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.google.com/"
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ Failed to download: {response.status_code}")
            return "Failed"

        # 3. Parse the Data (BeautifulSoup)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract the page title, or use "No Title" if missing
        page_title = soup.title.string if soup.title else "No Title"
       
       # --- NEW EXTRACTION LOGIC ---
        # 1. Get all H2 headings (main topics)
        headings = [h.get_text(strip=True) for h in soup.find_all('h2')]
        
        # 2. Get the first 5 external links
        links = [a['href'] for a in soup.find_all('a', href=True) if 'http' in a['href']]
        
        # 3. Create a rich data packet
        rich_content = {
            "status": "success",
            "scraped_at": str(response.elapsed.total_seconds()) + "s",
            "headings": headings[:5],  # Just the top 5
            "links_found": len(links),
            "sample_links": links[:5]  # Just the top 5
        }
        # -----------------------------
        
        # 4. Save to Database (Smart Update v2)
        db = SessionLocal()
        
        # Check if URL exists
        # We use .first() to grab the record if it exists
        existing_record = db.query(ScrapedData).filter(ScrapedData.url == url).first()
        
        if existing_record:
            # OPTION A: The Direct Update (Try this first)
            # This is the standard SQLAlchemy way. 
            # If VS Code complains, ignore it and run.
            existing_record.title = page_title # pyright: ignore[reportAttributeAccessIssue]
            existing_record.content = rich_content # pyright: ignore[reportAttributeAccessIssue]
            print(f"♻️ UPDATED: Refreshed data for '{page_title}'")
            
        else:
            # INSERT new record
            new_data = ScrapedData(
                url=url,
                title=page_title,
                content=rich_content
            )
            db.add(new_data)
            print(f"✅ CREATED: Saved new page '{page_title}'")
        
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"🔥 DB Error: {e}")
        finally:
            db.close()
            
        return "Success"

    except Exception as e:
        print(f"🔥 KITCHEN FIRE: {e}")
        return "Error"