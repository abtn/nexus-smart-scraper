import requests
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
from sqlalchemy.orm import Session
from src.database.models import ScrapedData, Source
import re
from datetime import datetime, timezone

class SitemapDiscovery:
    """
    Strategy 1: Sitemap Discovery.
    Locates sitemap.xml via robots.txt or common paths, parses XML, 
    and filters existing URLs.
    """

    def __init__(self, base_domain: str, db: Session, limit: int = 100):
        # Ensure proper schema if missing (e.g., if user passed "techcrunch.com", make it "https://techcrunch.com")
        if not base_domain.startswith('http'):
            base_domain = f"https://{base_domain}"
        
        self.base_domain = base_domain.rstrip('/')
        self.db = db
        self.limit = limit  # <--- Store limit
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Nexus-Crawler/1.0'})
        self.discovered_urls = set()

    def run(self):
        """Main execution flow."""
        print(f"🗺️ Starting Discovery for: {self.base_domain} (Limit: {self.limit})")

        # 1. Get Sitemap URLs
        sitemap_urls = self._find_sitemaps()
        
        if not sitemap_urls:
            print(f"⚠️ No sitemaps found for {self.base_domain}")
            return []

        # 2. Recursively parse all sitemaps (handles Sitemap Index files)
        self._crawl_sitemap_stack(sitemap_urls)

        print(f"🗺️ Found {len(self.discovered_urls)} raw URLs in sitemaps.")

        # 3. Filter out existing URLs
        new_urls = self._filter_existing_urls(list(self.discovered_urls))
        
        print(f"✅ {len(new_urls)} new URLs ready for queuing.")
        return new_urls

    def _find_sitemaps(self) -> list[str]:
        """
        Attempts to find sitemap URL via robots.txt or common guess.
        """
        sitemaps = []
        
        # Attempt A: Parse robots.txt
        # Often domains are like "sub.example.com", so we check the root of the provided domain
        parsed = urlparse(self.base_domain)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        
        try:
            print(f"🔍 Checking robots.txt at {robots_url}...")
            resp = self.session.get(robots_url, timeout=10)
            if resp.status_code == 200:
                # Regex to find 'Sitemap: <url>'
                matches = re.findall(r'Sitemap:\s*(.*)', resp.text, re.IGNORECASE)
                for match in matches:
                    sitemaps.append(match.strip())
                print(f"🤖 Found {len(matches)} sitemaps in robots.txt")
        except Exception as e:
            print(f"⚠️ Failed to fetch robots.txt: {e}")

        # Attempt B: Common guess if robots.txt failed or was empty
        if not sitemaps:
            common_paths = ['/sitemap.xml', '/sitemap_index.xml', '/sitemap.xml.gz']
            for path in common_paths:
                guess = f"{self.base_domain}{path}"
                try:
                    # Just a HEAD request to check existence
                    if self.session.head(guess, timeout=5).status_code == 200:
                        sitemaps.append(guess)
                        print(f"🔍 Guessed sitemap at: {guess}")
                        break
                except:
                    pass
        
        return list(set(sitemaps)) # Deduplicate

    def _crawl_sitemap_stack(self, urls: list[str]):
        """
        Recursively fetches sitemaps. Handles both standard sitemaps (urls) 
        and sitemap indexes (other sitemaps).
        """
        visited = set()
        
        # Limit recursion depth/count to avoid infinite loops or massive memory usage
        max_sitemaps_to_process = 50 
        processed_count = 0
        
        # Clone list to avoid modifying input
        stack = list(urls)
        
        while stack and processed_count < max_sitemaps_to_process:
            # --- CRITICAL CHECK: STOP IF LIMIT REACHED ---
            if len(self.discovered_urls) >= self.limit:
                print(f"🛑 Limit reached ({len(self.discovered_urls)} URLs). Stopping discovery.")
                break
            # ---------------------------------------------
            current_url = stack.pop(0)
            
            if current_url in visited:
                continue
            visited.add(current_url)
            processed_count += 1

            try:
                # If it's gzipped, requests usually handles it automatically if headers are correct
                resp = self.session.get(current_url, timeout=30)
                if resp.status_code != 200:
                    continue
                
                # Parse XML
                # Remove namespaces for easier parsing using a simple hack
                content = resp.content.decode('utf-8', errors='ignore')
                # Simple namespace stripping via Regex to make ElementTree happy
                content = re.sub(r' xmlns="[^"]+"', '', content, count=1)
                
                try:
                    root = ET.fromstring(content)
                except ET.ParseError:
                    print(f"❌ Malformed XML at {current_url}")
                    continue

                # Check if this is a Sitemap Index (contains <sitemap>)
                sitemap_tags = root.findall('sitemap')
                if sitemap_tags:
                    print(f"📂 Sitemap Index found at {current_url}. Found {len(sitemap_tags)} children.")
                    for s in sitemap_tags:
                        loc = s.find('loc')
                        if loc is not None and loc.text:
                            stack.append(loc.text.strip())
                
                # Check if this is a Urlset (contains <url>)
                else:
                    url_tags = root.findall('url')
                    if url_tags:
                        print(f"📄 Parsing {len(url_tags)} links from {current_url}")
                    
                        for u in reversed(url_tags):
                            if len(self.discovered_urls) >= self.limit:
                                break
                            
                            loc = u.find('loc')
                            if loc is not None and loc.text:
                                url_text = loc.text.strip()
                                if url_text.startswith('http'):
                                    self.discovered_urls.add(url_text)

            except Exception as e:
                print(f"❌ Error parsing sitemap {current_url}: {e}")

    def _filter_existing_urls(self, candidate_urls: list[str]) -> list[str]:
        """
        Bulk check against database to avoid re-processing known URLs.
        """
        if not candidate_urls:
            return []
        
        print("🔍 Checking database for duplicates...")
        
        # Split into chunks of 500 to prevent SQL variable limit errors
        chunk_size = 500
        new_urls = []
        
        for i in range(0, len(candidate_urls), chunk_size):
            chunk = candidate_urls[i:i + chunk_size]
            try:
                # Query DB for URLs in this chunk
                existing_in_db = self.db.query(ScrapedData.url)\
                    .filter(ScrapedData.url.in_(chunk))\
                    .all()
                
                existing_set = {row.url for row in existing_in_db}
                
                # Add only new ones
                for url in chunk:
                    if url not in existing_set:
                        new_urls.append(url)
            except Exception as e:
                print(f"❌ Database filtering error on chunk {i}: {e}")
        
        return new_urls