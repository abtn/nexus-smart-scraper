from tavily import TavilyClient # type: ignore
from duckduckgo_search import DDGS # type: ignore
from src.scraper.discovery import is_useful_link
from src.config import settings

def search_web(topic: str, max_results: int = 10) -> list[str]:
    """
    Uses Tavily (Primary) or DuckDuckGo (Fallback) to find relevant URLs.
    Optimized for AI agents to get high-quality, content-rich sources.
    """
    print(f"👀 Hunter: Looking for '{topic}'...")
    valid_urls = []

    # STRATEGY A: Tavily API (High Quality, Agent-Optimized)
    if settings.TAVILY_API_KEY:
        try:
            client = TavilyClient(api_key=settings.TAVILY_API_KEY)
            response = client.search(
                query=topic, 
                search_depth="advanced", 
                max_results=max_results,
                include_domains=[], 
                exclude_domains=["youtube.com", "facebook.com", "twitter.com", "tiktok.com"]
            )
            
            for result in response.get("results", []):
                url = result.get("url")
                if url and is_useful_link(url):
                    valid_urls.append(url)
                    print(f"  ✅ (Tavily) Found: {result.get('title')}")
            
            if valid_urls:
                return valid_urls
        except Exception as e:
            print(f"⚠️ Tavily failed: {e}. Falling back to DuckDuckGo...")

    # STRATEGY B: DuckDuckGo (Free Fallback)
    print(f"👀 Hunter: Using DuckDuckGo fallback...")
    try:
        with DDGS() as ddgs:
            raw_results = ddgs.text(topic, max_results=max_results * 2)
            
            if not raw_results:
                return []

            for result in raw_results:
                if len(valid_urls) >= max_results:
                    break

                url = result.get("href")
                if not url: continue

                # OPTIMIZATION: Removed is_allowed() check here.
                # The scrape_task will check compliance and fail gracefully if blocked.
                # This allows us to return a list faster.
                
                if is_useful_link(url):
                    valid_urls.append(url)
                    print(f"  ✅ (DDG) Found: {result.get('title')}")

    except Exception as e:
        print(f"🔻 Hunter Search Failed: {e}")

    return valid_urls