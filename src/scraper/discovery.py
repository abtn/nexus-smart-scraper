import requests
import re
from urllib.parse import urljoin, urlparse
from src.config import settings

# Heuristics to categorize sitemaps
PRIORITY_TERMS = ['news', 'en-us', 'uk', 'world', 'front-page', 'top']
# Terms to deprioritize or skip if you only want English
SKIP_TERMS = [
    'gahuza', 'arabic', 'hindi', 'urdu', 'pashto', 
    'mundo', 'brasil', 'russian', 'turkish', 'vietnamese',
    'bengali', 'tamil', 'nepali', 'zhongwen', 'indonesia'
]

def normalize_source(url: str) -> str:
    """
    Follows redirects to find the 'real' homepage.
    e.g., 'bbc.com' -> 'https://www.bbc.com/'
    """
    if not url.startswith('http'):
        url = 'https://' + url
        
    headers = {"User-Agent": settings.USER_AGENTS[0]}
    try:
        # HEAD request is fast; it just asks "Where does this go?"
        print(f"📍 Resolving base URL for: {url}...")
        resp = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
        final_url = resp.url.rstrip('/')
        if final_url != url.rstrip('/'):
            print(f"   ↳ Redirected to: {final_url}")
        return final_url
    except Exception as e:
        print(f"⚠️ Could not resolve URL {url}: {e}")
        return url

def score_sitemap(url: str) -> int:
    """
    Assigns a score to a sitemap URL to determine priority.
    Higher score = Scrape first.
    """
    url_lower = url.lower()
    score = 0
    
    # Gold Tier: Explicit News Sitemaps
    if 'sitemap-news' in url_lower or 'news-sitemap' in url_lower:
        score += 100
        
    # Silver Tier: English / Main keywords
    for term in PRIORITY_TERMS:
        if term in url_lower:
            score += 10
            
    # Penalty Tier: Known non-English services
    for term in SKIP_TERMS:
        if term in url_lower:
            score -= 1000 # Push to very bottom
            
    return score

def fetch_sitemaps(base_url):
    """
    Robust discovery that prioritizes English news.
    """
    # 1. Ensure we have the canonical URL (e.g. www.bbc.com)
    canonical_url = normalize_source(base_url)
    
    sitemaps = set()
    headers = {"User-Agent": settings.USER_AGENTS[0]}

    # 2. Try robots.txt
    robots_url = urljoin(canonical_url, "/robots.txt")
    print(f"🔍 Checking {robots_url}...")
    
    try:
        resp = requests.get(robots_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            found = re.findall(r'(?i)^Sitemap:\s*(.+)$', resp.text, re.MULTILINE)
            for s in found:
                sitemaps.add(s.strip())
    except Exception:
        pass

    # 3. Guessing Fallbacks (if robots.txt failed or was empty)
    common_paths = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-news.xml"]
    if not sitemaps:
        print("🕵️ Guessing common sitemap locations...")
        for path in common_paths:
            guess = urljoin(canonical_url, path)
            try:
                if requests.head(guess, headers=headers, timeout=5).status_code == 200:
                    sitemaps.add(guess)
            except:
                pass

    # 4. SORTING & FILTERING (The Critical Fix)
    sorted_sitemaps = sorted(list(sitemaps), key=score_sitemap, reverse=True)
    
    # Filter out the heavily penalized ones (score < -500) effectively skipping 'gahuza'
    final_list = [s for s in sorted_sitemaps if score_sitemap(s) > -500]
    
    # Logging for debug
    if final_list:
        print(f"✅ Selected Top 3 Sitemaps (out of {len(sitemaps)}):")
        for s in final_list[:3]:
            print(f"   - {s}")
            
    return final_list