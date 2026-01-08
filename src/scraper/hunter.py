from duckduckgo_search import DDGS  # pyright: ignore[reportMissingImports]
from src.scraper.compliance import is_allowed
from src.scraper.discovery import is_useful_link

def search_web(topic: str, max_results: int = 10) -> list[str]:
    """
    Uses DuckDuckGo to find relevant URLs for a topic.
    
    Filters:
    1. Compliance (Robots.txt)
    2. Usefulness (No PDFs, No YouTube, etc.)
    """
    print(f"👀 Hunter: Looking for '{topic}'...")
    
    valid_urls = []

    try:
        # DuckDuckGo Search
        # We use the context manager 'with DDGS()' to ensure session cleanup
        with DDGS() as ddgs:
            # .text() returns a generator of results
            raw_results = ddgs.text(topic, max_results=max_results * 2) # Fetch extra to account for filtering
            
            if not raw_results:
                print("👀 Hunter: No results found on DuckDuckGo.")
                return []

            for result in raw_results:
                if len(valid_urls) >= max_results:
                    break

                url = result.get("href")
                title = result.get("title")
                
                if not url: continue

                # 1. Filter: Usefulness (Extensions, Ads, YouTube)
                if not is_useful_link(url):
                    continue

                # 2. Filter: Compliance (Robots.txt)
                # Note: This adds network latency. We assume a standard user agent.
                try:
                    if not is_allowed(url, user_agent="Mozilla/5.0"):
                        print(f"  ⛔ Skipping {url} (Robots.txt blocked)")
                        continue
                except Exception as e:
                    print(f"  ⚠️ Could not check robots.txt for {url}: {e}")
                    # Fail-safe: Allow it, but log warning.
                    pass

                print(f"  ✅ Found Valid Target: {title} ({url})")
                valid_urls.append(url)

    except Exception as e:
        print(f"🔻 Hunter Search Failed: {e}")
        return []

    print(f"👀 Hunt Complete. Found {len(valid_urls)} valid targets.")
    return valid_urls