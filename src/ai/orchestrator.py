import time
import requests
from typing import List, Dict
from celery import group, chain
from src.config import settings
from src.database.connection import SessionLocal
from src.database.models import GeneratedContent, GeneratedContentStatus, ScrapedData, AIStatus
from src.ai.memory import search_memory
from src.scraper.hunter import search_web
# Deferred imports for tasks to avoid circular dependencies

class Orchestrator:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.db = SessionLocal()

    def _update_status(self, status: str, **kwargs):
        """Helper to update DB state safely."""
        try:
            task = self.db.query(GeneratedContent).filter(GeneratedContent.task_id == self.task_id).first()
            if task:
                task.status = status # pyright: ignore[reportAttributeAccessIssue]
                for k, v in kwargs.items():
                    setattr(task, k, v)
                self.db.commit()
        except Exception as e:
            print(f"❌ Orchestrator: Failed to update status: {e}")
            self.db.rollback()

    def _ask_brain(self, prompt: str, temperature=0.1) -> str:
        """Direct call to Ollama for decisions."""
        try:
            payload = {
                "model": settings.AI_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature}
            }
            resp = requests.post(f"{settings.AI_BASE_URL}/api/generate", json=payload, timeout=300)
            resp.raise_for_status()
            return resp.json().get('response', '').strip()
        except Exception as e:
            print(f"❌ Orchestrator: Brain call failed: {e}")
            return ""

    def phase_1_audit(self, user_prompt: str) -> Dict:
        """
        1. Search Memory. 2. Ask LLM: Is this enough?
        """
        print(f"🧠 [AUDIT] Analyzing memory for: {user_prompt}")
        memories = search_memory(user_prompt, limit=5)
        
        context_snippets = "\n".join([f"- {m.title}: {m.summary}" for m in memories]) or "No info."

        decision_prompt = f"""
        QUERY: {user_prompt}
        KNOWLEDGE: {context_snippets}
        
        Task: Do we have enough info to write a detailed blog post?
        Output strictly:
        YES
        or
        NO
        [Search Query 1]
        [Search Query 2]
        """
        
        response = self._ask_brain(decision_prompt)
        lines = [l.strip() for l in response.split('\n') if l.strip()]
        
        if not lines: return {'sufficient': False, 'queries': [user_prompt]}

        if lines[0].upper().startswith("YES"):
            return {'sufficient': True, 'queries': []}
        else:
            # Extract queries, skipping the "NO"
            queries = [q for q in lines[1:] if len(q) > 3][:3]
            if not queries: queries = [user_prompt] # Fallback
            return {'sufficient': False, 'queries': queries}

    def phase_2_gap_fill(self, queries: List[str], max_limit: int):
        """
        Hunt -> Scrape -> Wait Loop.
        """
        print(f"👀 [GAP-FILL] Hunting for: {queries}")
        # Import here to avoid circular import at top level
        from src.scraper.tasks import scrape_task, enrich_task
        
        all_urls = []
        for q in queries:
            try:
                urls = search_web(q, max_results=3)
                all_urls.extend(urls)
            except: pass
            
        unique_urls = list(set(all_urls))[:max_limit]
        if not unique_urls: return

        # 1. Dispatch Tasks
        for url in unique_urls:
            chain(scrape_task.s(url), enrich_task.s()).apply_async() # pyright: ignore[reportFunctionMemberAccess]

        # 2. Polling Wait Loop (Safer than blocking Celery)
        # We wait up to 90s for data to appear in DB
        print(f"⏳ Waiting for {len(unique_urls)} sources to process...")
        for _ in range(30): # 30 checks * 3 seconds = 90s max
            processed_count = 0
            for url in unique_urls:
                rec = self.db.query(ScrapedData).filter(ScrapedData.url == url).first()
                if rec and rec.ai_status == AIStatus.COMPLETED: # pyright: ignore[reportGeneralTypeIssues]
                    processed_count += 1
            
            if processed_count >= len(unique_urls):
                print("✅ [GAP-FILL] All sources ready.")
                break
            time.sleep(3)

    def phase_3_synthesis(self, user_prompt: str) -> str:
        """
        Re-read memory (now including new stuff) and write.
        """
        print("✍️ [WRITER] Synthesizing...")
        articles = search_memory(user_prompt, limit=10)
        
        if not articles: return "I tried to find information but failed."

        context = "\n\n".join([f"Source: {a.title}\n{a.summary}" for a in articles])
        
        writer_prompt = f"""
        Write a blog post about: "{user_prompt}"
        
        Use this context:
        {context}
        
        Format: Markdown (H2 headers). Cite sources.
        """
        return self._ask_brain(writer_prompt, temperature=0.7)

    def run(self, user_prompt: str, max_sources: int):
        try:
            # 1. Audit
            audit = self.phase_1_audit(user_prompt)
            
            # 2. Gap Fill
            if not audit['sufficient']:
                self._update_status(GeneratedContentStatus.PROCESSING, 
                                   search_queries=audit['queries'], 
                                   generated_text="Hunting for new data...")
                self.phase_2_gap_fill(audit['queries'], max_sources)
            
            # 3. Synthesis
            self._update_status(GeneratedContentStatus.PROCESSING, generated_text="Synthesizing final answer...")
            final_text = self.phase_3_synthesis(user_prompt)
            
            # 4. Finalize
            used_ids = [a.id for a in search_memory(user_prompt, limit=10)]
            self._update_status(GeneratedContentStatus.COMPLETED, 
                               generated_text=final_text, 
                               used_article_ids=used_ids)
            
        except Exception as e:
            print(f"🔥 Orchestrator Error: {e}")
            self._update_status(GeneratedContentStatus.FAILED, generated_text=str(e))
        finally:
            self.db.close()