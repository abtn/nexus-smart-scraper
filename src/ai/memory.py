from sqlalchemy import desc
# REMOVED: from pgvector.sqlalchemy import cos_distance  <-- THIS WAS THE ERROR
from src.database.connection import SessionLocal
from src.database.models import ScrapedData
from src.ai.client import Brain

def search_memory(query: str, limit: int = 5):
    """
    Finds articles semantically similar to the query.
    Returns: List[ScrapedData]
    """
    db = SessionLocal()
    try:
        # 1. Convert query to vector
        brain = Brain()
        query_vector = brain.generate_embedding(query)
        
        if not query_vector:
            return []

        # 2. Perform Vector Search (Cosine Distance)
        # CORRECTED: Use the method on the column itself
        results = db.query(ScrapedData)\
            .filter(ScrapedData.embedding.isnot(None))\
            .order_by(ScrapedData.embedding.cosine_distance(query_vector))\
            .limit(limit)\
            .all()
            
        return results
    except Exception as e:
        print(f"Memory Search Error: {e}")
        return []
    finally:
        db.close()