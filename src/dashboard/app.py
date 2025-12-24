import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
from src.config import settings

# 1. Setup Page
st.set_page_config(page_title="Scraper Dashboard", layout="wide")
st.title("🕷️ Scraper Dashboard")

# 2. Connect to Database
@st.cache_resource
def get_engine():
    return create_engine(settings.DB_URL)

engine = get_engine()

# 3. Fetch Data
def load_data():
    try:
        query = "SELECT id, url, title, created_at, content FROM scraped_data ORDER BY created_at DESC"
        df = pd.read_sql(query, engine)
        return df
    except Exception as e:
        st.error(f"Error connecting to DB: {e}")
        return pd.DataFrame()

# 4. Refresh Button
if st.button("🔄 Refresh Data"):
    st.cache_data.clear()

# --- NEW SECTION: ADD URL ---
st.sidebar.header("Add New Source")
new_url = st.sidebar.text_input("Enter URL to scrape:")

if st.sidebar.button("🚀 Launch Scraper"):
    if new_url:
        # FIX: Import the App object, not the function
        from src.scraper.tasks import app as celery_app
        
        # Send the task by NAME (String)
        # This tells Redis: "Hey, find the task named 'src.scraper.tasks.scrape_task' and run it"
        celery_app.send_task('src.scraper.tasks.scrape_task', args=[new_url])
        
        st.sidebar.success(f"Task queued! Check the main table shortly.")
    else:
        st.sidebar.warning("Please enter a URL.")
# -----------------------------

# 5. Display Stats
df = load_data()

col1, col2 = st.columns(2)
col1.metric("Total Pages Scraped", len(df))
if not df.empty:
    col2.metric("Latest Scrape", df.iloc[0]['url'])

# 6. Display Table
st.subheader("Recent Data")
if not df.empty:
    # Show the table
    st.dataframe(df)
    
    # Show raw JSON for selected row
    st.subheader("Inspect Content (JSON)")
    selected_id = st.selectbox("Select ID to inspect:", df['id'])
    if selected_id:
        row = df[df['id'] == selected_id].iloc[0]
        st.json(row['content'])
else:
    st.info("No data found yet. Run some tasks!")