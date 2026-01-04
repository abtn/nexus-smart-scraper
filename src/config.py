import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # Use localhost because Python runs in WSL and connects to Docker via mapped ports
    # FIX: Added defaults for Port ('5432') and Host ('postgres') to prevent "None" errors
    DB_URL = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST', 'postgres')}:{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB')}"
    REDIS_URL = os.getenv('REDIS_URL')

    # NEW: Timezone & Default Interval
    TIMEZONE = 'Asia/Tehran'
    DEFAULT_INTERVAL = 3600

   # --- AI STRATEGY ---
    AI_MAX_CONTEXT_TOKENS = 3000

    # 1. CLOUDFLARE (Priority #1)
    CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
    CF_API_TOKEN = os.getenv("CF_API_TOKEN")
    CF_MODEL = os.getenv("CF_MODEL", "@cf/meta/llama-3-8b-instruct")

    # 2. COHERE (Priority #2)
    COHERE_API_KEY = os.getenv("COHERE_API_KEY")
    COHERE_MODEL = os.getenv("COHERE_MODEL", "command-r")

    # 3. OPENROUTER (Priority #3)
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-small-3.1-24b-instruct:free")

    # 4. LOCAL OLLAMA (Priority #4 - Fallback)
    AI_BASE_URL = os.getenv("AI_BASE_URL", "http://ollama:11434") 
    AI_MODEL = os.getenv("AI_MODEL", "phi3.5") 
    
    # List of User-Agents
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ]
settings = Settings()