import streamlit as st
import pandas as pd
import plotly.express as px
import time
import requests
import json

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
        color: #333333;
        padding: 20px;
        border-radius: 10px;
        border-left: 5px solid #ff4b4b;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 15px;
        min-height: 180px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .streamlit-expanderHeader {
        background-color: #f8f9fa;
        color: #333333;
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
        force_single = st.checkbox("Single Page Scrape", help="Force this URL to be treated as a single article.")
        submitted = st.form_submit_button("⚡ Auto-Detect & Monitor")

        if submitted and new_url:
            success, msg = logic.create_and_trigger_job(new_url, custom_name, force_single)
            if success:
                st.toast(msg, icon="✅")
                time.sleep(1)
                st.rerun()
            else:
                st.error(msg)

    st.divider()

    # --- C. TOPIC HUNTER (Manual) ---
    st.subheader("👀 Topic Hunter")
    with st.form("hunt_form"):
        hunt_topic = st.text_input("Search Topic", placeholder="e.g. AI News")
        hunt_limit = st.slider("Max Results", 3, 10, 5)
        hunt_submitted = st.form_submit_button("🎯 Hunt Targets")
        
        if hunt_submitted and hunt_topic:
            with st.spinner("Hunting..."):
                success, msg, urls = logic.hunt_topic(hunt_topic, hunt_limit)
            if success:
                st.success(f"**Found {len(urls)} URLs:**")
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
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**{job.name}**")
                st.caption(f"{job.job_type.value.upper()} | {job.items_limit} items | {job.interval_seconds}s")
            with c2:
                if st.button("🗑️", key=f"del_{job.id}"):
                    logic.delete_job(job.id) # type: ignore
                    st.rerun()
            st.divider()

# ==========================================
# 3. MAIN AREA
# ==========================================
df = logic.load_analytics_data()

# Header
c_title, c_ref = st.columns([5, 1])
with c_title:
    st.title("🕸️ Nexus Command Center")
with c_ref:
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

# Tabs
tab_feed, tab_insights, tab_chat, tab_config = st.tabs(["🔥 Live Feed", "📊 Insights", "🤖 Agent Chat", "⚙️ Config"])

# ------------------------------------------
# TAB 1: LIVE FEED
# ------------------------------------------
with tab_feed:
    if df.empty:
        st.info("Waiting for intelligence... Add a URL in the sidebar.")
    else:
        heroes = df[df['ai_urgency'] >= 7].head(4)
        if not heroes.empty:
            st.subheader("🚨 Priority Intel")
            cols = st.columns(4)
            for i, (_, row) in enumerate(heroes.iterrows()):
                with cols[i % 4]:
                    st.markdown(f"""
                    <div class="hero-card">
                        <h4 style="margin:0; font-size:1.1em; line-height:1.4;">{row['title']}</h4>
                        <div style="margin-top:15px;">
                            <div style="font-weight:bold; color:#d9534f;">Score: {int(row['ai_urgency'])}/10</div>
                            <div style="color:#666; font-size:0.8em;">{row['ai_category']}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
        st.divider()
        st.subheader("🌊 Intelligence Stream")
        
        filter_col, _ = st.columns([2,4])
        cat_filter = filter_col.multiselect("Filter Category", df['ai_category'].unique())
        view_df = df[df['ai_category'].isin(cat_filter)] if cat_filter else df

        for _, row in view_df.iterrows():
            status_emoji = "✅" if row['ai_status'] == 'completed' else "⏳" if row['ai_status'] == 'pending' else "❌"
            with st.expander(f"{status_emoji}  |  {row['ai_category']}  |  {row['title']}"):
                mc1, mc2 = st.columns([3, 1])
                with mc1:
                    st.markdown(f"**Summary:** {row['summary']}")
                    if row['ai_tags']: st.caption(f"🏷️ {', '.join(row['ai_tags'])}")
                with mc2:
                    st.metric("Urgency", f"{row['ai_urgency']}/10")
                    st.caption(f"📅 {row['created_at'].strftime('%H:%M %p')}")
                    st.link_button("🔗 Read Source", row['url'])

# ------------------------------------------
# TAB 2: INSIGHTS
# ------------------------------------------
with tab_insights:
    if not df.empty:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Urgency Timeline")
            trend = df.set_index('created_at').resample('h')['ai_urgency'].mean().reset_index()
            st.plotly_chart(px.line(trend, x='created_at', y='ai_urgency', markers=True), use_container_width=True)
        with c2:
            st.subheader("Content Mix")
            st.plotly_chart(px.pie(df, names='ai_category', title='Category Distribution', hole=0.4), use_container_width=True)
    else:
        st.info("No data available.")

# ------------------------------------------
# TAB 3: AGENT CHAT (NEW)
# ------------------------------------------
with tab_chat:
    st.header("🤖 Nexus Agent")
    st.caption("Ask complex questions. The Agent will Audit memory, Hunt for gaps, and Synthesize an answer.")

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat Input
    if prompt := st.chat_input("Research topic..."):
        # 1. Add User Message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # 2. Call API & Poll
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            full_response = ""
            
            try:
                # Start Task
                # Using 'scraper_api' hostname for internal docker networking
                api_url = "http://scraper_api:8000/api/generate" 
                resp = requests.post(api_url, json={"prompt": prompt, "max_new_sources": 3}, timeout=10)
                
                if resp.status_code == 200:
                    task_data = resp.json()
                    task_id = task_data['task_id']
                    
                    # Polling Loop
                    status = "processing"
                    progress_text = "Starting workflow..."
                    
                    with st.status("🧠 Agent Working...", expanded=True) as status_box:
                        while status == "processing":
                            time.sleep(2)
                            # Check Status
                            stat_resp = requests.get(f"{api_url}/{task_id}", timeout=5)
                            if stat_resp.status_code == 200:
                                stat_data = stat_resp.json()
                                status = stat_data['status']
                                new_progress = stat_data.get('progress', 'Processing...')
                                
                                # Update Progress if changed
                                if new_progress != progress_text:
                                    status_box.write(f"👉 {new_progress}")
                                    progress_text = new_progress
                            else:
                                status = "failed"
                                full_response = "Error checking status."
                        
                        # Completion
                        if status == "completed":
                            status_box.update(label="✅ Complete!", state="complete", expanded=False)
                            result_resp = requests.get(f"{api_url}/{task_id}")
                            res_json = result_resp.json()
                            full_response = res_json.get('generated_text', 'No text generated.')
                            
                            # Add Footer with sources
                            articles_used = res_json.get('articles_used', 0)
                            full_response += f"\n\n---\n*📚 Analyzed {articles_used} sources from Memory & Web.*"
                        else:
                            status_box.update(label="❌ Failed", state="error")
                            full_response = "The Agent encountered an error."

                else:
                    full_response = f"API Error: {resp.status_code}"

            except Exception as e:
                full_response = f"Connection Error: {e}"

            # 3. Display & Save
            message_placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})

# ------------------------------------------
# TAB 4: CONFIGURATION
# ------------------------------------------
with tab_config:
    st.subheader("🛠️ Maintenance")
    if st.button("🧹 Clear Failed Tasks", use_container_width=True):
        success, msg = logic.clear_failed_tasks()
        if success:
            st.success(msg)
            time.sleep(1)
            st.rerun()
        else:
            st.error(msg)