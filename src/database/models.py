from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone

Base = declarative_base()

class Source(Base):
    __tablename__ = 'sources'
    id = Column(Integer, primary_key=True)
    domain = Column(String(255), unique=True, nullable=False)
    robots_url = Column(String(255))
    last_crawled = Column(DateTime)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    
    scraped_data = relationship("ScrapedData", back_populates="source")

class ScrapedLog(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True)
    level = Column(String(50))
    task_id = Column(String)
    url = Column(String)
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

class ScrapedData(Base):
    __tablename__ = 'scraped_data'
    id = Column(Integer, primary_key=True)
    
    source_id = Column(Integer, ForeignKey('sources.id'), nullable=True)
    source = relationship("Source", back_populates="scraped_data")

    url = Column(String, unique=True, nullable=False)
    title = Column(String)
    
    # --- NEW COLUMNS: Structured Content ---
    author = Column(String, nullable=True)
    published_date = Column(String, nullable=True) 
    summary = Column(Text, nullable=True)          
    main_image = Column(String, nullable=True)     
    clean_text = Column(Text, nullable=True)       
    # ----------------------------------------
    
    # --- AI ENRICHMENT ---
    ai_tags = Column(JSON, nullable=True)     # Stores ["tag1", "tag2"]
    ai_category = Column(String(100), nullable=True)
    ai_urgency = Column(Integer, nullable=True) 
    # ---------------------
    
    # Retain this for any extra data that doesn't fit the columns
    content = Column(JSON) 
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    
    # --- NEW TABLE --- Scheduled Jobs ---
class ScheduledJob(Base):
    __tablename__ = 'scheduled_jobs'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)  # e.g., "TechCrunch Home"
    url = Column(String, nullable=False)        # e.g., "https://techcrunch.com"
    interval_seconds = Column(Integer, default=3600) 
    is_active = Column(Boolean, default=True)   
    last_triggered_at = Column(DateTime, nullable=True) 
    created_at = Column(DateTime, default=datetime.now(timezone.utc))