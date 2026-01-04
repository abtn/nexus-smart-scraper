import requests
import json
import time # <--- NEW IMPORT
from tenacity import retry, stop_after_attempt, wait_exponential
from src.config import settings

class Brain:
    def __init__(self):
        # Ollama (Local) Config
        self.local_base_url = settings.AI_BASE_URL
        self.local_model = settings.AI_MODEL
        
        # OpenRouter (API) Config
        self.api_key = settings.OPENROUTER_API_KEY
        self.api_model = settings.OPENROUTER_MODEL
        self.api_url = settings.OPENROUTER_URL

        self._check_connection()

    def _check_connection(self):
        # 1. Check Local Ollama (Just a warning if down, as we might rely on API)
        try:
            requests.get(f"{self.local_base_url}/", timeout=2)
        except Exception as e:
            print(f"🧠 Brain Warning: Local Ollama unreachable: {e}")
        
        # 2. Check API Key presence
        if not self.api_key:
            print(f"🧠 Brain Info: No OpenRouter Key found. System will run in Local-Only mode.")

    # --- LOCAL LLM METHODS (Ollama) ---
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def think_local(self, prompt, system_prompt="", json_mode=False):
        payload = {
            "model": self.local_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_ctx": 4096}
        }

        if system_prompt:
            payload["system"] = system_prompt
        if json_mode:
            payload["format"] = "json"

        try:
            resp = requests.post(f"{self.local_base_url}/api/generate", json=payload, timeout=300)
            resp.raise_for_status()
            return resp.json().get('response', '')
        except Exception as e:
            print(f"🧠 Local Brain Error: {e}")
            return None

    # --- API LLM METHODS (OpenRouter) ---
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def think_api(self, system_prompt, user_prompt):
        """
        Uses OpenRouter (OpenAI compatible format).
        Faster, suited for summaries and tags.
        """
        if not self.api_key:
            raise ValueError("OpenRouter API Key is missing")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8501", # Required by OpenRouter
            "X-Title": "Scraper Project"
        }
        
        payload = {
            "model": self.api_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            # Low temperature for deterministic JSON
            "temperature": 0.1,
            # Optional: Some models support response_format={"type": "json_object"}
            # But for broader compatibility with free models, we rely on the prompt.
        }
        
        # 1. RATE LIMITING: Sleep 2 seconds before every request
        # This prevents hitting the API too hard in a loop
        print("⏳ API Pacing: Waiting 4s...")
        time.sleep(4) # Adjust as needed based on rate limits
        
        try:
            resp = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 429:
                print("⏳ Hit API Rate Limit (429). Waiting 10s...")
                time.sleep(10) # Wait and try one last time
                resp = requests.post(self.api_url, headers=headers, json=payload, timeout=60)
            
            resp.raise_for_status() # Raise error for other codes (500, etc)
            data = resp.json()
            # Extract content from OpenAI format response
            return data['choices'][0]['message']['content']
        except Exception as e:
            print(f"🌐 API Brain Error: {e}")
            raise e # Raise to trigger retry or fallback in main logic

    # --- MAIN ORCHESTRATOR ---
    def analyze_article(self, text: str) -> dict | None:
        """
        Decides which brain to use.
        1. Try OpenRouter API for speed (Summaries, Tags, Topics).
        2. Fallback to Local Ollama if API fails or key missing.
        """
        if not text: return None

        # Truncate to fit context window
        snippet = text[:settings.AI_MAX_CONTEXT_TOKENS]

        system_prompt = "You are an expert news analyst. Output valid JSON only, no markdown formatting."
        user_prompt = f"""
        Analyze this text:
        {snippet}

        Return JSON strictly in this format:
        {{
            "summary": "3 concise sentences",
            "tags": ["tag1", "tag2", "tag3"],
            "category": "Technology/Politics/Science/etc",
            "urgency": <int 1-10>
        }}
        """

        result_text = None
        
        # Attempt 1: Use OpenRouter API (Fast)
        if self.api_key:
            try:
                print("🌐 Using OpenRouter API for enrichment...")
                result_text = self.think_api(system_prompt, user_prompt)
            except Exception:
                print("⚠️ OpenRouter failed. preparing fallback...")
                result_text = None
        
        # Attempt 2: Fallback to Local Ollama
        if not result_text:
            print("🧠 Falling back to Local Ollama...")
            result_text = self.think_local(user_prompt, system_prompt=system_prompt, json_mode=True)

        # Parse Result
        if result_text:
            try:
                # Clean markdown code blocks if present (Common with LLMs)
                clean_text = result_text.replace("```json", "").replace("```", "").strip()
                return json.loads(clean_text)
            except json.JSONDecodeError as e:
                print(f"🧠 JSON Decode Error: {e}")
                print(f"📄 Bad Content: {result_text[:100]}...")
        return None

    def think_schedule(self, prompt: str) -> str | None:
        """
        Dedicated method for complex schedule management using Local LLM.
        This keeps the "Deep Thinking" on your metal, saving API tokens.
        """
        return self.think_local(prompt, json_mode=False)