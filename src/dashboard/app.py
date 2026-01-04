import streamlit as st
import pandas as pd
import plotly.express as px
from sqlalchemy import create_engine
from collections import Counter
import ast # Used to safely convert string representations of lists (e.g. "['Tag1', 'Tag2']") back into Python lists
from datetime import datetime 
# --- Pydantic Imports for Validation ---
from pydantic import TypeAdapter, HttpUrl, ValidationError

# --- Project Imports ---
from src.config import settings
from src.database.connection import SessionLocal
from src.database.models import ScheduledJob, Source
from urllib.parse import urlparse

# ==========================================
# 1. PAGE CONFIGURATION & STYLING
# ==========================================
st.set_page_config(
    page_title="AI Scraper Dashboard", 
    layout="wide", 
    page_icon="🕷️"
)

# Custom CSS for the Visual Feed (Cards, Badges, Pills)
st.markdown("""
<style>
    /* Card Container */
    .card {
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 20px;
        background-color: #ffffff;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        transition: transform 0.2s, box-shadow 0.2s;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        height: 100%;
    }
    .card:hover {
        transform: translateY(-3px);
        box-shadow: 0 5px 15px rgba(0,0,0,0.1);
    }
    
    /* Category Badge (Blue) */
    .badge-category {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.75em;
        font-weight: 600;
        background-color: #dbeafe;
        color: #1e3a8a;
        margin-right: 5px;
    }
    
    /* Urgency Badge (Red/Yellow/Green dynamic) */
    .badge-urgent {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 12px;
        font-size: 0.75em;
        font-weight: 600;
        color: #7f1d1d;
        margin-left: 5px;
    }
    .urgent-high { background-color: #fee2e2; color: #991b1b; }
    .urgent-medium { background-color: #fef3c7; color: #854d0e; }
    .urgent-low { background-color: #ecfdf5; color: #065f46; }
    
    /* Hash Tags */
    .tag-pill {
        display: inline-block;
        background-color: #f3f4f6;
        color: #4b5563;
        padding: 2px 8px;
        border-radius: 6px;
        font-size: 0.75em;
        margin-right: 4px;
        margin-top: 5px;
    }
</style>
""", unsafe_allow_html=True)

st.title("🕷️ AI-Powered Intelligence Dashboard")

# ==========================================
# 2. DATABASE CONNECTION & DATA LOADING
# ==========================================
@st.cache_resource
def get_engine():
    return create_engine(settings.DB_URL)

engine = get_engine()

@st.cache_data(ttl=5) # Cache data for 5 seconds
def load_data():
    try:
        # We now fetch ai_status and ai_error_log
        query = """
            SELECT id, url, title, created_at, 
                   ai_category, ai_urgency, ai_tags, 
                   summary, main_image, author,
                   ai_status, ai_error_log
            FROM scraped_data 
            ORDER BY created_at DESC
            LIMIT 50
        """
        df = pd.read_sql(query, engine)
        
        # --- Helper to parse the tags string back to list ---
        def parse_tags(tag_str):
            if not tag_str: return []
            try:
                # If it's already a list (unlikely from SQL but possible), return it
                if isinstance(tag_str, list): return tag_str
                # Safely evaluate string "['a', 'b']" to list ['a', 'b']
                return ast.literal_eval(tag_str)
            except:
                return []

        df['ai_tags'] = df['ai_tags'].apply(parse_tags)
        
        # Ensure urgency is numeric for calculations
        df['ai_urgency'] = pd.to_numeric(df['ai_urgency'], errors='coerce').fillna(0)
        
        return df
    except Exception as e:
        st.error(f"Error loading data: {e}")
        return pd.DataFrame()

# Refresh Button
if st.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# ==========================================
# 3. SIDEBAR: CONTROL PANEL
# ==========================================
with st.sidebar:
    st.header("⚙️ Control Panel")
    
    # --- PART A: MANUAL SCRAPER ---
    with st.expander("🚀 Launch Scraper", expanded=True):
        url_input = st.text_area("Enter URLs (one per line):", height=100)
        
        if st.button("Start Scraping"):
            if url_input:
                from celery import chain
                from src.scraper.tasks import scrape_task, enrich_task
                
                url_adapter = TypeAdapter(HttpUrl)
                urls = url_input.strip().split('\n')
                
                valid_count = 0
                invalid_urls = []
                
                for raw_url in urls:
                    url_str = raw_url.strip()
                    if not url_str: continue
                    
                    try:
                        url_adapter.validate_python(url_str)
                        # Chain: Scrape (Fast) -> Enrich (Slow)
                        chain(scrape_task.s(url_str), enrich_task.s()).apply_async() # type: ignore
                        valid_count += 1
                    except ValidationError:
                        invalid_urls.append(url_str)
                
                if valid_count > 0:
                    st.success(f"Queued {valid_count} tasks!")
                if invalid_urls:
                    st.error(f"Invalid URLs: {len(invalid_urls)}")
            else:
                st.warning("Enter a URL first.")

    st.divider()
    # ------- Temp placment -------
    with st.expander("🗺️ Site Discovery", expanded=True):
        st.caption("Auto-discover URLs from sitemaps.")
        
        crawl_db = SessionLocal()
        try:
            # Fetch existing sources for dropdown
            all_sources = crawl_db.query(Source).filter(Source.is_active == True).all()
            source_opts = {f"{s.domain}": s.id for s in all_sources}
            source_opts["✨ Create New Domain"] = "new" # pyright: ignore[reportArgumentType]
            
            # Select Box
            selected_label = st.selectbox("Target Domain:", list(source_opts.keys()))
            
            # Logic for New Domain
            new_domain_input = None
            target_source_id = None
            
            if source_opts[selected_label] == "new": # pyright: ignore[reportGeneralTypeIssues]
                new_domain_input = st.text_input("Enter Domain URL:", placeholder="https://techcrunch.com")
            else:
                target_source_id = source_opts[selected_label]

            # Limit Slider
            limit_val = st.slider("Max Articles:", 10, 200, 50)
            
            if st.button("Start Discovery"):
                # Case A: Creating New Source
                if new_domain_input:
                    try:
                        # Validate
                        TypeAdapter(HttpUrl).validate_python(new_domain_input)
                        parsed = urlparse(new_domain_input)
                        domain = parsed.netloc
                        
                        # Check DB
                        existing = crawl_db.query(Source).filter(Source.domain == domain).first()
                        if existing:
                            target_source_id = existing.id
                            st.info(f"Domain {domain} already exists. Using ID {target_source_id}.")
                        else:
                            # Create
                            new_source = Source(
                                domain=domain,
                                robots_url=f"{parsed.scheme}://{domain}/robots.txt",
                                last_crawled=datetime.now()
                            )
                            crawl_db.add(new_source)
                            crawl_db.commit()
                            crawl_db.refresh(new_source)
                            target_source_id = new_source.id
                            st.success(f"Created Source: {domain}")
                    except ValidationError:
                        st.error("Invalid URL.")
                    except Exception as e:
                        st.error(f"Error: {e}")

                # Case B: Launching Task
                if target_source_id: # pyright: ignore[reportGeneralTypeIssues]
                    from src.scraper.tasks import discover_sitemap_task
                    # Launch Async Task
                    discover_sitemap_task.delay(target_source_id, limit_val) # pyright: ignore[reportFunctionMemberAccess]
                    st.toast(f"Discovery launched for Source ID {target_source_id}!", icon="🕵️")
                else:
                    if not new_domain_input:
                        st.warning("Please select a domain.")
        finally:
            crawl_db.close()

    st.divider()
    # --- PART B: SCHEDULER MANAGEMENT ---
    st.subheader("🕒 Manage Schedules")
    
    with st.form("new_schedule"):
        s_name = st.text_input("Name", placeholder="e.g. Daily Tech News")
        s_url = st.text_input("URL", placeholder="https://example.com")
        s_int = st.number_input("Interval (sec)", min_value=60, value=3600, step=60)
        
        if st.form_submit_button("Create Schedule"):
            if s_name and s_url:
                db_add = SessionLocal()
                try:
                    job = ScheduledJob(name=s_name, url=s_url, interval_seconds=s_int, is_active=True)
                    db_add.add(job)
                    db_add.commit()
                    st.success("Saved!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    db_add.close()
    
    # List & Edit Schedules
    db_sched = SessionLocal()
    try:
        jobs = db_sched.query(ScheduledJob).order_by(ScheduledJob.created_at.desc()).all()
        if jobs:
            st.write("---")
            job_opts = {f"{j.id}. {j.name}": j.id for j in jobs}
            sel_job = st.selectbox("Select Task:", ["-- Select --"] + list(job_opts.keys()))
            
            if sel_job != "-- Select --":
                jid = job_opts[sel_job]
                jobj = next(j for j in jobs if j.id == jid) # type: ignore
                
                c1, c2 = st.columns(2)
                if c1.button("Toggle Active", key=f"tog_{jid}"):
                    jobj.is_active = not bool(jobj.is_active)  # type: ignore
                    db_sched.commit()
                    st.rerun()
                
                if c2.button("Delete", key=f"del_{jid}", type="primary"):
                    db_sched.delete(jobj)
                    db_sched.commit()
                    st.rerun()
                
                is_active_status = bool(jobj.is_active)
                st.caption(f"Status: {'✅ Active' if is_active_status else '❌ Inactive'}")
                st.caption(f"Interval: {jobj.interval_seconds}s")
    finally:
        db_sched.close()

    st.divider()

    # --- PART C: CRAWLER CONTROL (NEW) ---
    st.subheader("🕷️ Smart Crawler")

    with st.expander("Sitemap Discovery", expanded=False):
        st.caption("Auto-discover ALL URLs from a domain's sitemap.xml.")
        
        crawl_db = SessionLocal()
        try:
            all_sources = crawl_db.query(Source).all()
            source_opts = {f"{s.domain} (ID: {s.id})": s.id for s in all_sources}
            
            # Add "Custom" option to allow typing a new domain
            source_opts["-- Or Create New Domain --"] = "new" # pyright: ignore[reportArgumentType]
            
            # Reverse map for selectbox
            options_list = list(source_opts.keys())
            selected_option = st.selectbox("Select Domain:", options_list)
            
            new_domain_input = None
            if source_opts[selected_option] == "new": # pyright: ignore[reportGeneralTypeIssues]
                new_domain_input = st.text_input("New Domain", placeholder="https://techcrunch.com")
            # NEW: Limit Slider
            limit_val = st.slider("Max Articles to Queue:", 10, 500, 50)
            
            if st.button("🚀 Start Discovery", key="btn_discover"):
                source_to_use = None
                
                # 1. Determine Source
                if source_opts[selected_option] != "new": # pyright: ignore[reportGeneralTypeIssues]
                    source_id = source_opts[selected_option]
                    source_to_use = crawl_db.query(Source).get(source_id)
                elif new_domain_input:
                    # Validate & Create
                    try:
                        adapter = TypeAdapter(HttpUrl)
                        adapter.validate_python(new_domain_input)
                        
                        parsed = urlparse(new_domain_input)
                        domain = parsed.netloc
                        
                        # Check existence
                        existing = crawl_db.query(Source).filter(Source.domain == domain).first()
                        if existing:
                            source_to_use = existing
                        else:
                            # Create new
                            source_to_use = Source(
                                domain=domain,
                                robots_url=f"{parsed.scheme}://{domain}/robots.txt",
                                last_crawled=datetime.now()
                            )
                            crawl_db.add(source_to_use)
                            crawl_db.commit()
                            crawl_db.refresh(source_to_use)
                            st.success(f"Created new source: {domain}")
                            
                    except ValidationError:
                        st.error("Invalid URL format.")
                    except Exception as e:
                        st.error(f"Error creating source: {e}")

                # 2. Trigger Task
                if source_to_use:
                    from src.scraper.tasks import discover_sitemap_task
                    discover_sitemap_task.apply_async(args=[source_to_use.id, limit_val]) # pyright: ignore[reportFunctionMemberAccess]
                    st.toast(f"Discovery started (Limit: {limit_val})", icon="🕷️")
                else:
                    if not new_domain_input:
                         st.warning("Please select or enter a valid domain.")
        finally:
            crawl_db.close()

    # --- PART D: SYSTEM MAINTENANCE ---
    st.divider()
    st.subheader("🚑 System Maintenance")

    with st.expander("Rescue Stalled Tasks", expanded=False):
        st.caption("Push 'Pending' items from DB back into the AI Queue.")

        # Check for pending items
        pending_items = pd.read_sql("SELECT id, url FROM scraped_data WHERE ai_status = 'pending'", engine)

        st.info(f"**{len(pending_items)}** items waiting in Database.")

        if not pending_items.empty:
            if st.button("🚀 Re-Queue All Pending"):
                from src.scraper.tasks import enrich_task
        
                progress_text = "Dispatching tasks..."
                my_bar = st.progress(0, text=progress_text)
                
                count = 0
                total = len(pending_items)
        
                for index, row in pending_items.iterrows():
                    # Re-dispatch to AI Worker
                    enrich_task.s(row['id']).apply_async() # type: ignore
                    
                    count += 1
                    my_bar.progress(count / total, text=f"Queued {count}/{total}")
        
                st.success(f"Successfully re-queued {count} tasks!")
                import time
                time.sleep(1)
                st.rerun()

# ==========================================
# 4. MAIN CONTENT: ANALYTICS & FEED
# ==========================================
df = load_data()

if not df.empty:
    
    # --- PIPELINE STATUS ---
    st.header("📡 Pipeline Status")
    
    status_counts = df['ai_status'].value_counts()
    s_pending = status_counts.get('pending', 0)
    s_processing = status_counts.get('processing', 0)
    s_completed = status_counts.get('completed', 0)
    s_failed = status_counts.get('failed', 0)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("⏳ Pending", s_pending)
    col2.metric("🧠 Processing", s_processing, delta_color="off")
    col3.metric("✅ Completed", s_completed)
    col4.metric("❌ Failed", s_failed, delta_color="inverse")
    
    st.divider()

    # --- ANALYTICS (Completed Only) ---
    completed_df = df[df['ai_status'] == 'completed']

    st.header("📊 AI Insights")
    
    if not completed_df.empty:
        m1, m2, m3 = st.columns(3)
        
        total_arts = len(completed_df)
        avg_urg = completed_df['ai_urgency'].mean()
        top_cat = completed_df['ai_category'].mode()[0] if not completed_df['ai_category'].mode().empty else "N/A"
        
        m1.metric("Analyzed Articles", total_arts)
        m2.metric("Avg Urgency", f"{avg_urg:.1f}/10")
        m3.metric("Top Category", top_cat)
        
        st.divider()
        
        c1, c2 = st.columns(2)
        
        with c1:
            st.subheader("Content Mix")
            if not completed_df['ai_category'].dropna().empty:
                cat_counts = completed_df['ai_category'].value_counts()
                fig_pie = px.pie(values=cat_counts.values, names=cat_counts.index, hole=0.4)
                st.plotly_chart(fig_pie, width="stretch")
                
        with c2:
            st.subheader("Urgency Histogram")
            if not completed_df['ai_urgency'].dropna().empty:
                fig_hist = px.histogram(completed_df, x="ai_urgency", nbins=10, 
                                        color_discrete_sequence=['#636EFA'], title="Distribution of Scores")
                fig_hist.update_layout(bargap=0.1)
                st.plotly_chart(fig_hist, width="stretch")
                
        st.subheader("🏷️ Top 15 Trending Tags")
        all_tags = [tag for tags in completed_df['ai_tags'] for tag in tags]
        
        if all_tags:
            tag_counts = Counter(all_tags).most_common(15)
            tag_df = pd.DataFrame(tag_counts, columns=['Tag', 'Count'])
            fig_bar = px.bar(tag_df, x='Count', y='Tag', orientation='h', color='Count')
            st.plotly_chart(fig_bar, width="stretch")

        st.divider()
    else:
        st.info("Waiting for AI to complete analysis on pending items...")

    # ==========================================
    # 5. VISUAL NEWS FEED
    # ==========================================
    st.header("📰 Intelligence Feed")
    
    min_urg = st.slider("Filter by Urgency:", 1, 10, 1)
    
    filtered_df = df[
        (df['ai_status'] != 'completed') | 
        (df['ai_urgency'] >= min_urg)
    ]
    
    st.caption(f"Showing {len(filtered_df)} articles")
    
    cols = st.columns(3)
    
    for i, (_, row) in enumerate(filtered_df.iterrows()):
        
        # --- A. PENDING / PROCESSING / FAILED ---
        if row['ai_status'] != 'completed':
            if row['ai_status'] == 'processing':
                status_color = "#3b82f6" # Blue
                status_icon = "🧠"
                status_text = "AI IS THINKING..."
                extra_info = ""
            elif row['ai_status'] == 'failed':
                status_color = "#ef4444" # Red
                status_icon = "❌"
                status_text = "ANALYSIS FAILED"
                extra_info = f"<div style='color:red; font-size:0.8em; margin-top:5px;'>{row.get('ai_error_log', '')[:100]}</div>"
            else: # Pending
                status_color = "#9ca3af" # Gray
                status_icon = "⏳"
                status_text = "QUEUED FOR AI"
                extra_info = ""

            card_html = f"""
            <div class="card" style="border-left: 5px solid {status_color}; background-color: #f9fafb;">
                <div style="display:flex; justify-content:space-between;">
                    <h4 style="margin:0; font-size:1em; color: #333;">{row['title'] or row['url'][:50]}</h4>
                </div>
                <div style="margin-top:15px; font-weight:bold; color:{status_color};">
                    {status_icon} {status_text}
                </div>
                {extra_info}
                <div style="margin-top:auto; padding-top:10px; font-size:0.8em; color:gray;">
                    Scraped: {row['created_at'].strftime('%H:%M:%S')}
                </div>
            </div>
            """
            with cols[i % 3]:
                st.markdown(card_html, unsafe_allow_html=True)
            continue

        # --- B. COMPLETED ITEMS ---
        u_score = row['ai_urgency']
        u_class = "urgent-high" if u_score >= 8 else "urgent-medium" if u_score >= 5 else "urgent-low"
        border_col = "#991b1b" if u_score >= 8 else "#eab308" if u_score >= 5 else "#10b981"
        
        summary_text = row['summary'] if row['summary'] else "No summary available."
        if len(summary_text) > 150: summary_text = summary_text[:150] + "..."
        
        tags_html = "".join([f'<span class="tag-pill">#{t}</span>' for t in row['ai_tags'][:3]]) 
        
        card_html = f"""
        <div class="card" style="border-left: 5px solid {border_col};">
            <div style="display:flex; justify-content:space-between;">
                <h4 style="margin:0; font-size:1.1em;">{row['title'][:50]}...</h4>
                <span class="badge-urgent {u_class}">{int(u_score)}</span>
            </div>
            <div style="margin-top:5px; margin-bottom:10px;">
                <span class="badge-category">{row['ai_category']}</span>
            </div>
            <p style="font-size:0.9em; color:#444;">{summary_text}</p>
            <div style="margin-bottom:10px;">{tags_html}</div>
            <div style="margin-top:auto; font-size:0.8em; color:gray; display:flex; justify-content:space-between;">
                <span>{row['created_at'].strftime('%m-%d %H:%M')}</span>
                <a href="{row['url']}" target="_blank" style="color:#2563eb; text-decoration:none;">Read &rarr;</a>
            </div>
        </div>
        """
        
        with cols[i % 3]:
            st.markdown(card_html, unsafe_allow_html=True)

else:
    st.info("No data available yet. Add a URL in the sidebar to start!")