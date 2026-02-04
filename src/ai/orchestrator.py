import time
from typing import List, Dict
from urllib.parse import urlparse
from celery import group, chain
from src.database.connection import SessionLocal
from src.database.models import GeneratedContent, GeneratedContentStatus, ScrapedData, AIStatus, ScheduledJob, JobType, Source
from src.ai.memory import search_memory
from src.ai.client import Brain 
from src.scraper.hunter import search_web

class Orchestrator:
    def __init__(self, task_id: str):
        self.task_id = task_id
        self.db = SessionLocal()
        self.brain = Brain() # Use the unified brain

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

    def _promote_sources(self, article_ids: list[int]):
        """
        Phase 4: The Evolution.
        Converts one-off scraped articles into permanent monitoring jobs.
        
        Logic:
        1. Find domains of the provided article IDs.
        2. Check if a DISCOVERY job already exists for that domain.
        3. If not, create a Source record (if missing).
        4. Create a ScheduledJob (Type: DISCOVERY) to monitor it.
        """
        if not article_ids:
            return

        print(f"🧬 [EVOLUTION] Analyzing {len(article_ids)} sources for promotion...")

        # 1. Fetch the article objects from DB
        articles = self.db.query(ScrapedData).filter(ScrapedData.id.in_(article_ids)).all()

        for article in articles:
            if not article.url: continue # pyright: ignore[reportGeneralTypeIssues]

            # 2. Extract Domain
            try:
                parsed_url = urlparse(article.url) # type: ignore
                domain = parsed_url.netloc
            except Exception:
                continue
            
            if not domain: continue

            # 3. Check if we are already monitoring this domain
            # We look for a DISCOVERY job that references this domain
            existing_job = self.db.query(ScheduledJob).filter(
                ScheduledJob.job_type == JobType.DISCOVERY,
                ScheduledJob.url.contains(domain)
            ).first()

            if existing_job:
                continue

            print(f"  🚀 Promoting new high-value domain: {domain}")

            # 4. Ensure Source record exists (Required for Discovery tasks)
            source = self.db.query(Source).filter(Source.domain == domain).first()
            if not source:
                source = Source(
                    domain=domain,
                    robots_url=f"{parsed_url.scheme}://{domain}/robots.txt"
                )
                self.db.add(source)
                self.db.flush() # Flush to generate the ID before commit

            # 5. Create Scheduled Job
            # We use a safe default interval (24h) for new unknown sources.
            job_url = f"{parsed_url.scheme}://{domain}"
            
            new_job = ScheduledJob(
                name=f"Auto-Discovery: {domain}",
                url=job_url,
                interval_seconds=86400, # 24 Hours
                is_active=True,
                job_type=JobType.DISCOVERY,
                items_limit=5 
            )
            self.db.add(new_job)

        try:
            self.db.commit()
            print("✅ [EVOLUTION] Promotion complete. New domains added to watchlist.")
        except Exception as e:
            print(f"❌ [EVOLUTION] Failed to save promotions: {e}")
            self.db.rollback()

    def phase_1_audit(self, user_prompt: str) -> Dict:
        """
        1. Search Memory. 2. Ask Smart API (not just local): Is this enough?
        """
        print(f"🧠 [AUDIT] Analyzing memory for: {user_prompt}")
        memories = search_memory(user_prompt, limit=5)

        context_snippets = "\n".join([f"- {m.title}: {m.summary}" for m in memories]) or "No info."

        # Use the Waterfall Brain for logic
        decision_prompt = f"""
        QUERY: {user_prompt}
        
        CURRENT KNOWLEDGE BASE (Top 5 matches):
        {context_snippets}

        TASK:
        Analyze if the 'Current Knowledge Base' contains enough specific, recent, and high-quality information 
        to write a comprehensive blog post about the QUERY.
        
        Rules:
        - If info is generic or old, answer NO.
        - If info answers the "Who, What, Where, When", answer YES.

        Output Format:
        Line 1: YES or NO
        Line 2+: (If NO) 3 specific search queries to find missing info.
        """

        response = self.brain.chat(
            system_prompt="You are an intelligent research auditor. Output strictly text.",
            user_prompt=decision_prompt
        )

        if not response: return {'sufficient': False, 'queries': [user_prompt]}

        lines = [l.strip() for l in response.split('\n') if l.strip()]
        if not lines: return {'sufficient': False, 'queries': [user_prompt]}

        if lines[0].upper().startswith("YES"):
            return {'sufficient': True, 'queries': []}
        else:
            queries = [q for q in lines[1:] if len(q) > 3][:3]
            if not queries: queries = [user_prompt]
            return {'sufficient': False, 'queries': queries}

    def phase_2_gap_fill(self, queries: List[str], max_limit: int):
        """
        Hunt -> Scrape -> Wait Loop.
        """
        print(f"👀 [GAP-FILL] Hunting for: {queries}")
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
            chain(scrape_task.s(url), enrich_task.s()).apply_async() # type: ignore

        # 2. Polling Wait Loop
        print(f"⏳ Waiting for {len(unique_urls)} sources to process...")
        for i in range(40): 
            processed_count = 0
            for url in unique_urls:
                rec = self.db.query(ScrapedData).filter(ScrapedData.url == url).first()
                if rec and rec.ai_status == AIStatus.COMPLETED: # pyright: ignore[reportGeneralTypeIssues]
                    processed_count += 1
            
            if processed_count >= len(unique_urls):
                print(f"✅ [GAP-FILL] All {len(unique_urls)} sources ready.")
                break
            
            if processed_count > 0 and i > 20:
                print(f"⚠️ [GAP-FILL] Timeout reached. Proceeding with {processed_count}/{len(unique_urls)} sources.")
                break
                
            time.sleep(3)

    def phase_3_synthesis(self, user_prompt: str) -> str:
        """
        Re-read memory and write using the Smart API.
        """
        print("✍️ [WRITER] Synthesizing...")
        articles = search_memory(user_prompt, limit=10)
        
        if not articles: return "I tried to find information but failed."

        context = "\n\n".join([f"Source: {a.title}\nContent: {a.summary}" for a in articles])
        
        writer_prompt = f"""
        Write a high-quality, engaging blog post about: "{user_prompt}"
        
        Instructions:
        - Use ONLY the provided context below.
        - If the context is insufficient, state that clearly in the conclusion.
        - Use Markdown (H2 headers).
        - Include a 'References' section at the end listing the sources used.
        
        Context:
        {context}
        """
        
        return self.brain.chat(
            system_prompt="You are an expert tech writer.",
            user_prompt=writer_prompt,
            temperature=0.7 
        ) # pyright: ignore[reportReturnType]

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

            # --- NEW: PHASE 4 EVOLUTION ---
            # If we successfully wrote content, learn from the sources we used.
            if final_text and used_ids:
                self._promote_sources(used_ids) # pyright: ignore[reportArgumentType]
            
        except Exception as e:
            print(f"🔥 Orchestrator Error: {e}")
            self._update_status(GeneratedContentStatus.FAILED, generated_text=str(e))
        finally:
            self.db.close()