from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean, ForeignKey, Enum
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone
import enum
from pgvector.sqlalchemy import Vector # pyright: ignore[reportMissingImports]
from src.config import settings

# 1. Define the Enum FIRST so it can be used below
class AIStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

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
    
    # --- Structured Content ---
    author = Column(String, nullable=True)
    published_date = Column(String, nullable=True) 
    summary = Column(Text, nullable=True)          
    main_image = Column(String, nullable=True)     
    clean_text = Column(Text, nullable=True)       
    
    # --- NEW: MEMORY COLUMN ---
    # Stores the vector representation (768 dimensions for nomic-embed-text)
    embedding = Column(Vector(settings.EMBEDDING_DIM), nullable=True)

    content = Column(JSON)
    
    # --- AI METADATA ---
    # Now this works because AIStatus is defined above
    ai_status = Column(String(20), default=AIStatus.PENDING, index=True)
    ai_error_log = Column(Text, nullable=True)

    # --- AI ENRICHMENT ---
    ai_tags = Column(JSON, nullable=True)
    ai_category = Column(String(100), nullable=True)
    ai_urgency = Column(Integer, nullable=True) 
    
    content = Column(JSON) 
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

class JobType(str, enum.Enum):
    RSS = "rss"             # Monitors an RSS feed URL
    DISCOVERY = "discovery" # Monitors a Domain (Sitemap/BFS)
    SINGLE = "single"       # Monitors a specific Article URL (Legacy)

class ScheduledJob(Base):
    __tablename__ = 'scheduled_jobs'

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    url = Column(String, nullable=False)
    job_type = Column(Enum(JobType), default=JobType.SINGLE, nullable=False)
    
    # --- NEW COLUMN ---
    items_limit = Column(Integer, default=10) 
    
    interval_seconds = Column(Integer, default=3600)
    is_active = Column(Boolean, default=True)
    last_triggered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    
# 1. Add Status Enum
class GeneratedContentStatus(str, enum.Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

# 2. Add GeneratedContent Table
class GeneratedContent(Base):
    __tablename__ = 'generated_content'
    
    id = Column(Integer, primary_key=True)
    task_id = Column(String(64), unique=True, index=True, nullable=False)
    user_prompt = Column(Text, nullable=False)
    generated_text = Column(Text, nullable=True)
    
    # Status Management
    status = Column(String(20), default=GeneratedContentStatus.PROCESSING, index=True)
    
    # Metadata (Stored as JSON)
    search_queries = Column(JSON, nullable=True)     
    used_article_ids = Column(JSON, nullable=True) 
    
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))