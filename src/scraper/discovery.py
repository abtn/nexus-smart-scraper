import requests
import re
from urllib.parse import urljoin, urlparse
from collections import deque
from bs4 import BeautifulSoup
from src.config import settings

# --- CONFIGURATION ---
# Terms that suggest a page lists articles (Navigation/Crawler nodes)
INDEX_KEYWORDS = ['blog', 'news', 'article', 'post', 'story', 'feed', 'tag', 'category', 'archive']
# Terms that suggest a specific piece of content (Target/Scrape nodes)
CONTENT_KEYWORDS = ['read', 'details', 'single', 'view', 'full-story', '/202', '/203', '/204', '/205']

# Heuristics to categorize sitemaps
PRIORITY_TERMS = ['news', 'en-us', 'uk', 'world', 'front-page', 'top']
# Terms to deprioritize or skip
SKIP_TERMS = [
    'gahuza', 'arabic', 'hindi', 'urdu', 'pashto',
    'mundo', 'brasil', 'russian', 'turkish', 'vietnamese',
    'bengali', 'tamil', 'nepali', 'zhongwen', 'indonesia'
]

def normalize_source(url: str) -> str:
    """Follows redirects to find the 'real' homepage."""
    if not url.startswith('http'):
        url = 'https://' + url

    headers = {"User-Agent": settings.USER_AGENTS[0]}
    try:
        # HEAD request is fast
        print(f"📍 Resolving base URL for: {url}...")
        resp = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
        final_url = resp.url.rstrip('/')
        return final_url
    except Exception as e:
        print(f"⚠️ Could not resolve URL {url}: {e}")
        return url

def score_sitemap(url: str) -> int:
    """Assigns a score to a sitemap URL to determine priority."""
    url_lower = url.lower()
    score = 0
    if 'sitemap-news' in url_lower or 'news-sitemap' in url_lower:
        score += 100
    for term in PRIORITY_TERMS:
        if term in url_lower:
            score += 10
    for term in SKIP_TERMS:
        if term in url_lower:
            score -= 1000 
    return score

def fetch_sitemaps(base_url):
    """Standard sitemap discovery."""
    canonical_url = normalize_source(base_url)
    sitemaps = set()
    headers = {"User-Agent": settings.USER_AGENTS[0]}

    # 1. Try robots.txt
    robots_url = urljoin(canonical_url, "/robots.txt")
    try:
        resp = requests.get(robots_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            found = re.findall(r'(?i)^Sitemap:\s*(.+)$', resp.text, re.MULTILINE)
            for s in found:
                sitemaps.add(s.strip())
    except Exception:
        pass

    # 2. Guessing Fallbacks
    if not sitemaps:
        common_paths = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-news.xml"]
        for path in common_paths:
            guess = urljoin(canonical_url, path)
            try:
                if requests.head(guess, headers=headers, timeout=5).status_code == 200:
                    sitemaps.add(guess)
            except:
                pass

    # 3. Sort
    sorted_sitemaps = sorted(list(sitemaps), key=score_sitemap, reverse=True)
    final_list = [s for s in sorted_sitemaps if score_sitemap(s) > -500]
    
    if final_list:
        print(f"✅ Sitemaps found: {len(final_list)}")
    return final_list

# ==========================================
# NEW: RECURSIVE CRAWLER (BFS)
# ==========================================

def is_internal_link(link, domain):
    """Checks if a link belongs to the domain."""
    try:
        parsed_link = urlparse(link)
        parsed_domain = urlparse(domain)
        # Compare netlocs (ignoring www. prefix for looser matching if needed)
        return parsed_link.netloc.replace('www.', '') == parsed_domain.netloc.replace('www.', '')
    except:
        return False

# Filters out non-useful links
def is_useful_link(url):
    """
    Filters out static assets, login pages, and irrelevant files.
    """
    url_lower = url.lower()

    # Exclude assets
    if any(url_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.css', '.js', '.pdf', '.zip', '.mp4']):
        return False

    # Exclude utilities AND Ads/Redirects AND Video Platforms (Phase 2 Update)
    excluded_terms = [
        'login', 'register', 'signin', 'signup', 'contact', 'cart',
        'checkout', 'account', '#', 'javascript:',
        '/ads/', '/redirect/', '/banner/', '/click/',
        'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com' # <--- NEW: Video filters
    ]

    if any(x in url_lower for x in excluded_terms):
        return False

    return True

def classify_link(url_path):
    """
    Determines if a URL is likely an 'article' (target) or an 'index' (crawl deeper).
    """
    url_lower = url_path.lower()
    
    # 1. Specific Date Patterns usually indicate articles (/2024/01/...)
    if re.search(r'/20[0-9]{2}/', url_lower):
        return 'article'
    if re.search(r'/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/', url_lower):
        return 'article'
    
    # 2. ID patterns (e.g., /article/12345 or -12345.html)
    if re.search(r'[-/]\d{4,}(\.html)?$', url_lower):
        return 'article'

    # 3. Index patterns (contain keywords but might be lists)
    for kw in INDEX_KEYWORDS:
        if f'/{kw}' in url_lower:
            return 'index'
            
    return 'unknown'

def crawl_recursive(base_url, max_articles=50, depth_limit=2):
    """
    Performs a BFS crawl to find article links when sitemaps fail.
    """
    print(f"🕷️ Starting Recursive Crawl for: {base_url}")
    
    domain = normalize_source(base_url)
    visited = set()
    article_links = set()
    
    # Queue: stores (url, current_depth)
    queue = deque([(domain, 0)])
    
    # Reuse session for performance
    session = requests.Session()
    session.headers.update({"User-Agent": settings.USER_AGENTS[0]})

    while queue and len(article_links) < max_articles:
        current_url, depth = queue.popleft()
        
        if current_url in visited or depth > depth_limit:
            continue
            
        visited.add(current_url)
        
        try:
            # Fetch Page
            response = session.get(current_url, timeout=10)
            if response.status_code != 200:
                continue
                
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract Links
            found_this_round = 0
            
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                # Convert relative to absolute
                absolute_url = urljoin(current_url, href) # pyright: ignore[reportArgumentType]
                
                # Filters
                if not is_internal_link(absolute_url, domain): continue
                if not is_useful_link(absolute_url): continue
                
                # Classification
                path = urlparse(absolute_url).path
                link_type = classify_link(path)
                
                # Logic: Is it an article?
                if link_type == 'article' and absolute_url not in article_links:
                    article_links.add(absolute_url)
                    found_this_round += 1
                    print(f"  🎯 Found Article: {absolute_url}")
                    
                    if len(article_links) >= max_articles:
                        break
                
                # Logic: Is it an index page we should dig deeper into?
                elif link_type == 'index' and absolute_url not in visited:
                    # Prevent circular queues
                    if absolute_url not in [x[0] for x in queue]:
                        queue.append((absolute_url, depth + 1))

        except Exception as e:
            print(f"  ⚠️ Error crawling {current_url}: {e}")
            continue

    print(f"✅ Recursive Crawl finished. Found {len(article_links)} articles.")
    return list(article_links)