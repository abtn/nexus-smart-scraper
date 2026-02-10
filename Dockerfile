# Dockerfile
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Prevent Python from writing .pyc files
ENV PYTHONDONTWRITEBYTECODE=1
# Ensure logs are flushed immediately
ENV PYTHONUNBUFFERED=1

# Upgrade pip first
RUN pip install --no-cache-dir --upgrade pip

# Install dependencies
COPY requirements.txt .

# --- ROBUST INSTALL COMMAND ---
# 1. --timeout 1000: Wait much longer for slow connections
# 2. --retries 10: Retry downloads 10 times before failing
# 3. --index-url: Use a mirror if PyPI is slow (Optional, stick to default first)
RUN pip install --timeout 1000 --retries 10 -r requirements.txt

# Copy the rest of the application
COPY . .

# Default command (can be overridden by docker-compose)
CMD ["python", "-m", "celery", "-A", "src.scraper.tasks", "worker", "--loglevel=info"]