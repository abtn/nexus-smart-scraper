import requests
import json
from tenacity import retry, stop_after_attempt, wait_exponential
from src.config import settings

class Brain:
    def __init__(self):
        self.base_url = settings.AI_BASE_URL
        self.model = settings.AI_MODEL
        # Helper check
        self._check_connection()

    def _check_connection(self):
        try:
            requests.get(f"{self.base_url}/", timeout=2)
        except Exception as e:
            print(f"🧠 Brain Warning: Ollama service unreachable: {e}")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def think(self, prompt, system_prompt="", json_mode=False):
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_ctx": 4096}
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        if json_mode:
            payload["format"] = "json"

        try:
            # Use /api/generate endpoint
            resp = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=300)
            resp.raise_for_status()
            return resp.json().get('response', '')
        except Exception as e:
            print(f"🧠 Brain Error: {e}")
            return None

    def analyze_article(self, text: str) -> dict | None:
        if not text: return None
        
        # Safe truncation
        snippet = text[:settings.AI_MAX_CONTEXT_TOKENS]
        
        system_prompt = "You are an expert news analyst. Output valid JSON only."
        user_prompt = f"""
        Analyze this text:
        {snippet}
        
        Return JSON with:
        {{
            "summary": "3 concise sentences",
            "tags": ["tag1", "tag2", "tag3"],
            "category": "Technology/Politics/Science/etc",
            "urgency": <int 1-10>
        }}
        """

        result = self.think(user_prompt, system_prompt=system_prompt, json_mode=True)
        if result:
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                pass
        return None