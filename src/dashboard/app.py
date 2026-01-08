import streamlit as st
import pandas as pd
import plotly.express as px
import time

# Import our Logic Layer
import src.dashboard.logic as logic

# ==========================================
# 1. SETUP & STYLING
# ==========================================
st.set_page_config(page_title="Nexus Command", layout="wide", page_icon="🕸️")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; }
    /* Hero Card Style */
    .hero-card {
        background-color: #ffffff;
        color: #333333;             /* FIX: Force dark text on white background */
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #ff4b4b;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 15px;
        height: auto;               /* FIX: Allow card to grow with text */
        min-height: 180px;          /* Minimum height for alignment */
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    
    /* List styling */
    .streamlit-expanderHeader {
        background-color: #f8f9fa;
        color: #333333;             /* Fix contrast in expanders too */
        font-size: 0.95em;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. SIDEBAR: SMART INPUT & MONITORS
# ==========================================
with st.sidebar:
    st.header("🎮 Nexus Control")
    
    # --- A. MAGIC INPUT ---
    st.caption("🚀 **Add New Source**")
    with st.form("smart_add_form"):
        new_url = st.text_input("Paste URL (RSS, Home, or Article)", placeholder="https://...")
        custom_name = st.text_input("Name (Optional)", placeholder="e.g. TechCrunch")
        
        # New Checkbox
        force_single = st.checkbox("Single Page Scrape", help="Force this URL to be treated as a single article, ignoring auto-detection.")

        submitted = st.form_submit_button("⚡ Auto-Detect & Monitor")
        
        if submitted and new_url:
            # Pass the checkbox value to the logic
            success, msg = logic.create_and_trigger_job(new_url, custom_name, force_single)
            
            if success:
                st.toast(msg, icon="✅")
                time.sleep(1)
                st.rerun()
            else:
                st.error(msg)

    st.divider()

# --- NEW: C. TOPIC HUNTER ---
    st.subheader("👀 Topic Hunter")
    st.caption("Find new sources for a specific topic.")
    
    with st.form("hunt_form"):
        hunt_topic = st.text_input("Search Topic", placeholder="e.g. Quantum Computing Advances")
        hunt_limit = st.slider("Max Results", 5, 20, 10)
        hunt_submitted = st.form_submit_button("🎯 Hunt Targets")
        
        if hunt_submitted and hunt_topic:
            with st.spinner("Hunting the web..."):
                success, msg, urls = logic.hunt_topic(hunt_topic, hunt_limit)
            
            if success:
                st.toast(msg, icon="👀")
                st.success(f"**Discovered {len(urls)} URLs:**")
                for url in urls:
                    st.code(url, language="text")
            else:
                st.error(msg)

    st.divider()

    # --- B. ACTIVE MONITORS ---
    st.subheader("📡 Active Monitors")
    jobs = logic.get_active_jobs()
    
    if not jobs:
        st.info("No active monitors.")
    else:
        for job in jobs:
            # Compact view
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**{job.name}**")
                st.caption(f"{job.job_type.value.upper()} | {job.items_limit} items | {job.interval_seconds}s")
            with c2:
                if st.button("🗑️", key=f"del_{job.id}", help="Delete Job"):
                    logic.delete_job(job.id) # pyright: ignore[reportArgumentType]
                    st.rerun()
            st.divider()

# ==========================================
# 3. MAIN AREA: DATA LOADER
# ==========================================
df = logic.load_analytics_data()

# Header
c_title, c_ref = st.columns([5, 1])
with c_title:
    st.title("🕸️ Nexus Command Center")
with c_ref:
    # FIX: Replaced use_container_width with width="stretch"
    if st.button("🔄 Refresh", width="stretch"):
        st.rerun()

# Tabs
tab_feed, tab_insights, tab_config = st.tabs(["🔥 Live Feed", "📊 Insights", "⚙️ Config"])

# ==========================================
# TAB 1: LIVE FEED
# ==========================================
with tab_feed:
    if df.empty:
        st.info("Waiting for intelligence... Add a URL in the sidebar.")
    else:
        # 1. Hero Cards (Urgency >= 7)
        heroes = df[df['ai_urgency'] >= 7].head(4)
        if not heroes.empty:
            st.subheader("🚨 Priority Intel")
            cols = st.columns(4)
            for i, (_, row) in enumerate(heroes.iterrows()):
                with cols[i % 4]:
                    # TRUNCATION REMOVED: using row['title'] directly
                    st.markdown(f"""
                    <div class="hero-card">
                        <h4 style="margin:0; font-size:1.1em; line-height:1.4; word-wrap: break-word;">
                            {row['title']}
                        </h4>
                        <div style="margin-top:15px;">
                            <div style="font-weight:bold; color:#d9534f; font-size:0.9em;">
                                Score: {int(row['ai_urgency'])}/10
                            </div>
                            <div style="color:#666; font-size:0.8em; margin-top:5px;">
                                {row['ai_category']}
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
        
        st.divider()
        
        # 2. Data River (The rest)
        st.subheader("🌊 Intelligence Stream")
        
        # Filters
        filter_col, _ = st.columns([2,4])
        cat_filter = filter_col.multiselect("Filter Category", df['ai_category'].unique())
        
        view_df = df
        if cat_filter:
            view_df = df[df['ai_category'].isin(cat_filter)]

        for _, row in view_df.iterrows():
            # Status Indicator
            status_emoji = "✅" if row['ai_status'] == 'completed' else "⏳" if row['ai_status'] == 'pending' else "❌"
            
            with st.expander(f"{status_emoji}  |  {row['ai_category']}  |  {row['title']}"):
                mc1, mc2 = st.columns([3, 1])
                with mc1:
                    st.markdown(f"**Summary:** {row['summary']}")
                    if row['ai_tags']:
                        st.caption(f"🏷️ {', '.join(row['ai_tags'])}")
                    if row['ai_error_log']:
                        st.error(f"Log: {row['ai_error_log']}")
                with mc2:
                    st.metric("Urgency", f"{row['ai_urgency']}/10")
                    st.caption(f"📅 {row['created_at'].strftime('%H:%M %p')}")
                    st.link_button("🔗 Read Source", row['url'])

# ==========================================
# TAB 2: INSIGHTS
# ==========================================
with tab_insights:
    if not df.empty:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Urgency Timeline")
            # FIX: Replaced 'H' with 'h' for pandas deprecation
            trend = df.set_index('created_at').resample('h')['ai_urgency'].mean().reset_index()
            fig_line = px.line(trend, x='created_at', y='ai_urgency', markers=True)
            # FIX: Updated width for plotly
            st.plotly_chart(fig_line, width='stretch')
            
        with c2:
            st.subheader("Content Mix")
            fig_pie = px.pie(df, names='ai_category', title='Category Distribution', hole=0.4)
            # FIX: Updated width for plotly
            st.plotly_chart(fig_pie, width='stretch')
    else:
        st.info("No data for analytics.")

# ==========================================
# TAB 3: CONFIGURATION
# ==========================================
with tab_config:
    st.subheader("🛠️ Maintenance")
    st.write("Database management tools.")
    
    col_m1, _ = st.columns([1, 4])
    
    with col_m1:
        # IMPLEMENTED: Connected to Logic Layer
        if st.button("🧹 Clear Failed Tasks", width="stretch"):
            success, msg = logic.clear_failed_tasks()
            if success:
                st.success(msg)
                time.sleep(1)
                st.rerun()
            else:
                st.error(msg)