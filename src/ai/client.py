import requests
import json
import re
import time
from src.config import settings

class Brain:
    def __init__(self):
        # Define the priority order
        self.providers = [
            ("cloudflare", self._think_cloudflare),
            ("cohere", self._think_cohere),
            ("openrouter", self._think_openrouter),
            ("local", self._think_ollama)
        ]

    def _clean_json(self, raw_text):
        """Robust cleaner to extract JSON object from LLM chatter."""
        if not raw_text: return None
        text = raw_text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Regex fallback
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return None

    def analyze_article(self, text: str) -> dict | None:
        if not text: return None
        
        snippet = text[:settings.AI_MAX_CONTEXT_TOKENS]
        
        system_prompt = """You are a news analyst API. Strictly output JSON. No markdown."""
        user_prompt = f"""
        Analyze this text:
        {snippet}
        
        Return JSON with this schema:
        {{
            "summary": "3 concise sentences",
            "tags": ["tag1", "tag2", "tag3"],
            "category": "Technology/Politics/Science/etc",
            "urgency": integer_1_to_10
        }}
        """

        # --- THE WATERFALL LOOP ---
        for provider_name, strategy_func in self.providers:
            try:
                # 🛡️ RATE LIMIT GUARD: 4 Second Wait
                # This ensures we respect Cohere's 20 req/min (1 per 3s)
                # and prevents 429 errors on free tiers.
                time.sleep(4) 
                
                print(f"🧠 Brain: Trying provider '{provider_name}'...")
                
                # Execute Strategy
                raw_result = strategy_func(user_prompt, system_prompt)
                
                # If we got a result, clean it and return
                if raw_result:
                    cleaned_data = self._clean_json(raw_result)
                    if cleaned_data:
                        print(f"✅ Brain: Success via '{provider_name}'")
                        return cleaned_data
                    else:
                        print(f"⚠️ Brain: '{provider_name}' returned invalid JSON.")
                        # Continue to next provider if JSON was bad
                        
            except Exception as e:
                print(f"❌ Brain: '{provider_name}' failed: {e}")
                # Continue to next provider
        
        print("🔥 Brain: All providers failed.")
        return None

    # --- PROVIDER STRATEGIES ---

    def _think_cloudflare(self, user_prompt, system_prompt):
        if not settings.CF_ACCOUNT_ID or not settings.CF_API_TOKEN:
            raise ValueError("Missing Cloudflare Credentials")
            
        url = f"https://api.cloudflare.com/client/v4/accounts/{settings.CF_ACCOUNT_ID}/ai/run/{settings.CF_MODEL}"
        headers = {"Authorization": f"Bearer {settings.CF_API_TOKEN}"}
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
        # Short timeout because we want to fail fast and try the next one
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        return resp.json()['result']['response']

    def _think_cohere(self, user_prompt, system_prompt):
        if not settings.COHERE_API_KEY:
            raise ValueError("Missing Cohere API Key")

        headers = {
            "Authorization": f"Bearer {settings.COHERE_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {
            "model": settings.COHERE_MODEL,
            "message": user_prompt,
            "temperature": 0.3,
            "preamble": system_prompt,
            "response_format": {"type": "json_object"}
        }
        resp = requests.post("https://api.cohere.com/v1/chat", headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        return resp.json().get('text', '')

    def _think_openrouter(self, user_prompt, system_prompt):
        if not settings.OPENROUTER_API_KEY:
            raise ValueError("Missing OpenRouter API Key")

        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000", 
        }
        payload = {
            "model": settings.OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3
        }
        resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']

    def _think_ollama(self, user_prompt, system_prompt):
        # Health check just for local
        try:
            requests.get(f"{settings.AI_BASE_URL}/", timeout=1)
        except:
            raise ConnectionError("Ollama Service not running")

        payload = {
            "model": settings.AI_MODEL,
            "prompt": user_prompt,
            "stream": False,
            "options": {"num_ctx": 4096},
            "format": "json"
        }
        if system_prompt: payload["system"] = system_prompt

        # Longer timeout for local inference
        resp = requests.post(f"{settings.AI_BASE_URL}/api/generate", json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json().get('response', '')