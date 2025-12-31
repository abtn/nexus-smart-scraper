import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # Use localhost because Python runs in WSL and connects to Docker via mapped ports
    DB_URL = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DB')}"
    REDIS_URL = os.getenv('REDIS_URL')
    
    # NEW: Timezone & Default Interval
    TIMEZONE = 'Asia/Tehran'
    DEFAULT_INTERVAL = 3600
    
    # --- AI CONFIGURATION ---
    # Default to container name 'ollama'
    AI_BASE_URL = os.getenv("AI_BASE_URL", "http://ollama:11434") 
    AI_MODEL = os.getenv("AI_MODEL", "phi3.5") 
    AI_MAX_CONTEXT_TOKENS = 3000 
    # ------------------------
    
    # List of User-Agents to rotate
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]
settings = Settings()