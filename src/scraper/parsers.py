import trafilatura
import json
from bs4 import BeautifulSoup

def parse_smart(html_content: str, url: str) -> dict:
    """
    Uses Trafilatura to extract the 'meat' of the article.
    Falls back to BeautifulSoup for basic metadata if Trafilatura fails.
    """
    # 1. Initialize default keys to prevent KeyError
    data = {
        'title': None,
        'author': None,
        'published_date': None,
        'clean_text': None,
        'main_image': None,
        'summary': None
    }
    
    # 2. Trafilatura Extraction
    extracted = trafilatura.extract(
        html_content, 
        url=url,
        include_images=True,
        include_links=False,
        output_format='json',
        with_metadata=True
    )
    
    if extracted:
        try:
            t_data = json.loads(extracted)
            
            # Update data only if Trafilatura found values
            data['title'] = t_data.get('title')
            data['author'] = t_data.get('author')
            data['published_date'] = t_data.get('date')
            data['clean_text'] = t_data.get('text')
            data['main_image'] = t_data.get('image')
            
            text_body = t_data.get('text', '')
            excerpt = t_data.get('excerpt')
            data['summary'] = excerpt if excerpt else (text_body[:200] + "..." if len(text_body) > 200 else text_body)
        except json.JSONDecodeError:
            # Trafilatura returned bad JSON, keep defaults (None)
            pass
    
    # 3. Fallback / Augmentation (BeautifulSoup)
    # If we still don't have a title, try to grab it with BeautifulSoup
    if not data.get('title'):
        soup = BeautifulSoup(html_content, 'html.parser')
        data['title'] = soup.title.get_text(strip=True) if soup.title else "No Title"

    return data