from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone # <--- Import timezone

Base = declarative_base()

class Source(Base):
    __tablename__ = 'sources'
    id = Column(Integer, primary_key=True)
    domain = Column(String(255), unique=True, nullable=False)
    robots_url = Column(String(255))
    last_crawled = Column(DateTime)
    is_active = Column(Boolean, default=True)
    # Updated to timezone-aware UTC
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    
    scraped_data = relationship("ScrapedData", back_populates="source")

class ScrapedLog(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True)
    level = Column(String(50))
    task_id = Column(String)
    url = Column(String)
    message = Column(Text)
    # Updated to timezone-aware UTC
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

class ScrapedData(Base):
    __tablename__ = 'scraped_data'
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey('sources.id'), nullable=True)
    source = relationship("Source", back_populates="scraped_data")
    url = Column(String, unique=True, nullable=False)
    title = Column(String)
    content = Column(JSON)
    # Updated to timezone-aware UTC
    created_at = Column(DateTime, default=datetime.now(timezone.utc))