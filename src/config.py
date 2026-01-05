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

    # --- 1. AVALAI (New - High Priority) ---
    AVALAI_API_KEY = os.getenv("AVALAI_API_KEY")
    AVALAI_BASE_URL = os.getenv("AVALAI_BASE_URL", "https://api.avalai.ir/v1/chat/completions")
    AVALAI_MODEL = os.getenv("AVALAI_MODEL", "gemma-3n-e2b-it")

    # --- 2. CLOUDFLARE ---
    CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
    CF_API_TOKEN = os.getenv("CF_API_TOKEN")
    CF_MODEL = os.getenv("CF_MODEL", "@cf/meta/llama-3-8b-instruct")

    # --- 3. COHERE ---
    COHERE_API_KEY = os.getenv("COHERE_API_KEY")
    COHERE_MODEL = os.getenv("COHERE_MODEL", "command-r")

    # --- 4. OPENROUTER ---
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-small-3.1-24b-instruct:free")

    # --- 5. LOCAL OLLAMA ---
    AI_BASE_URL = os.getenv("AI_BASE_URL", "http://ollama:11434") 
    AI_MODEL = os.getenv("AI_MODEL", "phi3.5") 
    
    # List of Modern User-Agents
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
    ]
settings = Settings()