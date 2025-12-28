# Enterprise Web Scraper 🕷️

A high-performance, containerized web scraping platform built with Python, Celery, and Streamlit. Designed for concurrency, resilience, and strict compliance.

[![CI Pipeline](https://github.com/abtn/scrapping-project-for-abtin/actions/workflows/ci.yml/badge.svg)](https://github.com/abtn/scrapping-project-for-abtin/actions/workflows/ci.yml)

## 🏗️ Architecture

- **Ingestion**: Streamlit Dashboard for bulk URL input with Pydantic validation.
- **Queue**: Redis for task buffering.
- **Workers**: Celery with Gevent pool (50+ threads) for high-speed I/O.
- **Storage**: PostgreSQL with SQLAlchemy ORM and Alembic migrations.
- **Monitoring**: Flower for real-time worker metrics + Custom DB Logging.
- **Resilience**: Robots.txt enforcement, User-Agent rotation, and exponential backoff retries.

## 🚀 Getting Started

### Prerequisites
- Docker & Docker Compose

### Running the App
1. Clone the repo:
   ```bash
   git clone https://github.com/YOUR_USERNAME/scrapping-project-for-abtin.git
   cd scrapping-project-for-abtin
   ```

2. Create a `.env` file:
   ```ini
   POSTGRES_USER=admin
   POSTGRES_PASSWORD=adminpass
   POSTGRES_DB=scraper_db
   POSTGRES_HOST=postgres
   REDIS_URL=redis://redis:6379/0
   ```

3. Launch the stack:
   ```bash
   docker compose up --build -d
   ```

4. Access the interfaces:
   - **Dashboard**: http://localhost:8501
   - **Flower (Monitoring)**: http://localhost:5555

## 🧪 Testing

Run the test suite locally:
```bash
pip install -r requirements.txt
pytest tests/ -v
```

## 🛠️ Tech Stack

- **Python 3.10**
- **Celery / Redis / PostgreSQL**
- **BeautifulSoup4 / Requests / Tenacity**
- **Streamlit / Pandas**
- **Pytest / GitHub Actions**
```



