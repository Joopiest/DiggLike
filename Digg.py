import streamlit as st
import requests
import feedparser
from bs4 import BeautifulSoup
import time
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import streamlit.components.v1 as components
import os
from datetime import datetime, timezone, timedelta

# --- Background Daemon System Globals ---
LATEST_NEWS = []
SEEN_IDS = set()

BG_CONFIG = {
    "interval_minutes": 0,
    "sources": [],
    "last_fetch_time": 0,
    "running": False
}

# --- Page Config ---
st.set_page_config(page_title="My Local Digg", page_icon="📈", layout="wide")

# --- Custom CSS for aesthetic ---
st.markdown("""
    <style>
    .post-container {
        border: 1px solid #ddd;
        border-radius: 10px;
        padding: 15px;
        margin-bottom: 15px;
        background-color: #f9f9f9;
        display: flex;
        flex-direction: row;
        align-items: flex-start;
    }
    .score-box {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        width: 80px;
        margin-right: 20px;
    }
    .score-number {
        font-size: 24px;
        font-weight: bold;
        color: #ff4500;
        margin: 5px 0;
    }
    .post-content {
        flex-grow: 1;
    }
    .post-title {
        font-size: 20px;
        font-weight: bold;
        color: #222;
        text-decoration: none;
    }
    .post-source {
        font-size: 14px;
        color: #888;
        margin-top: 5px;
    }
    .tag {
        background-color: #e0e0e0;
        padding: 3px 8px;
        border-radius: 12px;
        font-size: 12px;
        color: #555;
        margin-right: 10px;
    }
    </style>
""", unsafe_allow_html=True)

# --- State Management ---
if "user_votes" not in st.session_state:
    st.session_state.user_votes = {} # dict mapping item_id -> vote modifier (+1 or -1)
if "fetched_items" not in st.session_state:
    st.session_state.fetched_items = []

# --- Data Fetching Functions ---
import re

def assign_topic_category(text_to_search, fallback_category):
    text_lower = text_to_search.lower()
    
    # Use word boundaries for English keywords to prevent 'ai' matching 'thailand'
    keywords = {
        "ข่าวด่วน (Breaking)": [
            'ด่วน', 'ระทึก', 'สลด', 'เสียชีวิต', 'จับกุม', 'ระเบิด', 'ไฟไหม้', 'สึนามิ', 'แผ่นดินไหว', 'อุบัติเหตุ', 'กราดยิง', 'สงคราม', 'วิกฤต',
            r'\bbreaking', r'\burgent', r'\bexplosion', r'\bearthquake', r'\btsunami', r'\bkill', r'\bdead', r'\bwar\b', r'\bcrisis', r'\bshoot', r'\battack', r'\bbomb', r'\bcrash'
        ],
        "การเมือง (Politics)": [
            'นายก', 'สภา', 'การเมือง', 'พรรค', 'ประท้วง', 'รัฐบาล', 'เลือกตั้ง', 'กฎหมาย', 'ศาล', 'ม็อบ', 'ทหาร', 'ตำรวจ',
            r'\bpolitic', r'\bgovernment', r'\belection', r'\bpresident', r'\btrump\b', r'\bbiden\b', r'\bdemocrat', r'\brepublican', r'\bparliament', r'\bminister'
        ],
        "เทคโนโลยี (Tech)": [
            'เทคโนโลยี', 'มือถือ', 'แอป', 'ไอที', 'คอมพิวเตอร์', 'ซอฟต์แวร์', 'สมาร์ทโฟน', 'อินเทอร์เน็ต',
            r'\bai\b', r'\bapple\b', r'\bgoogle\b', r'\bmicrosoft\b', r'\btech', r'\bsoftware', r'\bhardware', r'\bcyber', r'\bsmartphone', r'\brobot', r'\bsamsung\b', r'\bnvidia\b', r'\bopenai\b', r'\bchatgpt\b', r'\biphone\b', r'\bandroid\b'
        ],
        "เศรษฐกิจ (Economy)": [
            'เศรษฐกิจ', 'ส่งออก', 'นำเข้า', 'จีดีพี', 'เงินเฟ้อ', 'นโยบายการเงิน', 'พาณิชย์', 'อุตสาหกรรม',
            r'\beconomy', r'\beconomic', r'\binflation', r'\btrade\b', r'\bgdp\b', r'\bexport', r'\bimport', r'\brecession', r'\bmacroeconomics'
        ],
        "การเงิน (Finance)": [
            'หุ้น', 'ดอกเบี้ย', 'คริปโต', 'ธนาคาร', 'ลงทุน', 'กองทุน', 'ทองคำ', 'ตลาดหลักทรัพย์', 'กำไร', 'รายได้',
            r'\bfinance', r'\bbank', r'\bstock', r'\bcrypto', r'\binvestment', r'\bbitcoin\b', r'\bwall street', r'\bmarket', r'\bfund\b', r'\bbtc\b', r'\beth\b'
        ],
        "การศึกษา (Education)": [
            'การศึกษา', 'โรงเรียน', 'มหาวิทยาลัย', 'นักเรียน', 'นิสิต', 'นักศึกษา', 'สอบ', 'ทุน', 'ครู', 'อาจารย์',
            r'\beducation', r'\bschool', r'\buniversity', r'\bstudent', r'\bteacher', r'\bcollege', r'\bexam', r'\bscholarship'
        ],
        "บันเทิง (Entertainment)": [
            'บันเทิง', 'ดารา', 'ภาพยนตร์', 'เพลง', 'คอนเสิร์ต', 'หนัง', 'ละคร', 'ซีรีส์', 'ศิลปิน', 'ไอดอล', 'ดราม่า', 'รีวิวหนัง',
            r'\bentertainment', r'\bmovie', r'\bmusic', r'\bcelebrity', r'\bhollywood\b', r'\bnetflix\b', r'\bactor', r'\bactress', r'\bsinger', r'\bpop\b', r'\banime\b', r'\bkpop\b'
        ]
    }
    
    for category, words in keywords.items():
        for word in words:
            if word.startswith(r'\b'):
                # Regex search for English words
                if re.search(word, text_lower):
                    return category
            else:
                # Normal substring search for Thai words
                if word in text_lower:
                    return category
            
    return fallback_category

def fetch_reddit():
    url = "https://www.reddit.com/r/popular/top.json?limit=15&t=day"
    headers = {"User-agent": "DiggCloneBot/0.1"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        data = response.json()
        items = []
        for child in data.get('data', {}).get('children', []):
            post = child['data']
            search_text = post['title'] + " " + post.get('subreddit', '')
            items.append({
                "id": f"reddit_{post['id']}",
                "title": post['title'],
                "url": f"https://www.reddit.com{post['permalink']}",
                "source": "Reddit",
                "base_score": post['score'],
                "category": assign_topic_category(search_text, "ทั่วไป (General)")
            })
        return items
    except Exception as e:
        # Reddit often rate-limits or returns empty — fail silently, retry next cycle
        return []

def fetch_rss(feed_url, source_name, category):
    try:
        feed = feedparser.parse(feed_url)
        items = []
        for entry in feed.entries[:10]:
            tags = " ".join([t.term for t in entry.get('tags', [])]) if hasattr(entry, 'tags') else ""
            search_text = entry.title + " " + tags
            items.append({
                "id": f"rss_{source_name}_{entry.id if hasattr(entry, 'id') else entry.link}",
                "title": entry.title,
                "url": entry.link,
                "source": source_name,
                "base_score": 100, # Base arbitrary score for news
                "category": assign_topic_category(search_text, category)
            })
        return items
    except Exception as e:
        return []

def fetch_pantip():
    url = "https://pantip.com/home/feed/pantip_trend" # Attempting trend feed or homepage
    headers = {"User-agent": "Mozilla/5.0"}
    try:
        res = requests.get("https://pantip.com/", headers=headers, timeout=5)
        soup = BeautifulSoup(res.content, 'html.parser')
        items = []
        # Find links that look like topics
        links = soup.find_all('a', href=True)
        added_urls = set()
        for link in links:
            href = link['href']
            title = link.text.strip()
            if '/topic/' in href and len(title) > 20 and href not in added_urls:
                items.append({
                    "id": f"pantip_{href.split('/')[-1]}",
                    "title": title,
                    "url": href if href.startswith('http') else f"https://pantip.com{href}",
                    "source": "Pantip",
                    "base_score": 250, # High base score for Pantip trends
                    "category": assign_topic_category(title, "ทั่วไป (General)")
                })
                added_urls.add(href)
            if len(items) >= 10:
                break
        return items
    except Exception as e:
        return []

def get_raw_data(sources_selected):
    all_items = []
    if "Reddit (Global Trends)" in sources_selected:
        all_items.extend(fetch_reddit())
    if "BBC (Global News)" in sources_selected:
        all_items.extend(fetch_rss("http://feeds.bbci.co.uk/news/rss.xml", "BBC News", "ทั่วไป (General)"))
    if "Google News (Thailand)" in sources_selected:
        all_items.extend(fetch_rss("https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th", "Google News TH", "ทั่วไป (General)"))
    if "Google News TH (IT)" in sources_selected:
        all_items.extend(fetch_rss("https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB?hl=th&gl=TH&ceid=TH:th", "Google News TH (IT)", "เทคโนโลยี (Tech)"))
    if "Pantip (Thai Trends)" in sources_selected:
        all_items.extend(fetch_pantip())
    if "CNN (Global News)" in sources_selected:
        all_items.extend(fetch_rss("http://rss.cnn.com/rss/edition.rss", "CNN", "ทั่วไป (General)"))
    if "Al Jazeera (Global News)" in sources_selected:
        all_items.extend(fetch_rss("https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera", "ทั่วไป (General)"))
    if "Thairath (Thai News)" in sources_selected:
        all_items.extend(fetch_rss("https://www.thairath.co.th/rss/news", "Thairath", "ทั่วไป (General)"))
    if "Blognone (IT News)" in sources_selected:
        all_items.extend(fetch_rss("https://www.blognone.com/atom.xml", "Blognone", "เทคโนโลยี (Tech)"))
    if "The Standard (Thai News)" in sources_selected:
        all_items.extend(fetch_rss("https://thestandard.co/feed/", "The Standard", "ทั่วไป (General)"))
    if "Krungthep Turakij (Business News)" in sources_selected:
        all_items.extend(fetch_rss("https://www.bangkokbiznews.com/rss/news", "Krungthep Turakij", "เศรษฐกิจ (Economy)"))
    if "Spaceth.co (Space News)" in sources_selected:
        all_items.extend(fetch_rss("https://spaceth.co/feed/", "Spaceth.co", "เทคโนโลยี (Tech)"))
    if "Physics.org (Science News)" in sources_selected:
        all_items.extend(fetch_rss("https://phys.org/rss-feed/", "Phys.org", "เทคโนโลยี (Tech)"))
    if "Space.com (Space News)" in sources_selected:
        all_items.extend(fetch_rss("https://www.space.com/feeds/all", "Space.com", "เทคโนโลยี (Tech)"))
    return all_items

def fetch_all_data(sources_selected):
    with st.spinner("Fetching trending data..."):
        all_items = get_raw_data(sources_selected)
        st.session_state.fetched_items = all_items
        fetch_time = time.time()
        st.session_state['last_fetch_time'] = fetch_time
        BG_CONFIG["last_fetch_time"] = fetch_time
        # Write to file so background thread and UI stay in sync
        try:
            file_path = os.path.join(os.path.dirname(__file__), 'last_fetch.txt')
            with open(file_path, 'w') as f:
                f.write(str(fetch_time))
        except:
            pass
        
        # Mark these as SEEN so the background thread doesn't resend them
        global SEEN_IDS
        for item in all_items:
            SEEN_IDS.add(item['id'])

# API server removed for Streamlit Cloud compatibility

def bg_fetch_loop():
    global SEEN_IDS, LATEST_NEWS, BG_CONFIG
    while True:
        interval = BG_CONFIG["interval_minutes"]
        if interval > 0 and BG_CONFIG.get("running", False):
            now = time.time()
            if now - BG_CONFIG["last_fetch_time"] > interval * 60:
                try:
                    new_items = get_raw_data(BG_CONFIG["sources"])
                    for item in new_items:
                        if item['id'] not in SEEN_IDS:
                            SEEN_IDS.add(item['id'])
                            LATEST_NEWS.append({
                                "id": item['id'], 
                                "title": item['title'], 
                                "category": item['category'], 
                                "score": item['base_score'],
                                "url": item['url'],
                                "source": item['source']
                            })
                    BG_CONFIG["last_fetch_time"] = time.time()
                    # Write to file so Streamlit UI can read it
                    try:
                        file_path = os.path.join(os.path.dirname(__file__), 'last_fetch.txt')
                        with open(file_path, 'w') as f:
                            f.write(str(BG_CONFIG["last_fetch_time"]))
                    except:
                        pass
                except Exception as e:
                    pass
        time.sleep(10)

if 'bg_fetcher_started' not in st.session_state:
    threading.Thread(target=bg_fetch_loop, daemon=True).start()
    st.session_state.bg_fetcher_started = True

# --- UI Layout ---

st.title("📈 My Local Digg Aggregator")
st.markdown("Your curated trending feed. **Digg** what you like, **Bury** what you don't. The best content rises to the top.")

# Sidebar - Preferences
st.sidebar.header("⚙️ Your Preferences")
search_query = st.sidebar.text_input("🔍 ค้นหาข่าว", "")
sources_data = [
    ("Reddit (Global Trends)", "🟧 **Reddit**"),
    ("Pantip (Thai Trends)", "🟪 **Pantip**"),
    ("Google News (Thailand)", "🟦 **Google News TH**"),
    ("Google News TH (IT)", "🟨 **Google News TH (IT)**"),
    ("BBC (Global News)", "🟥 **BBC News**"),
    ("CNN (Global News)", "🔴 **CNN**"),
    ("Al Jazeera (Global News)", "🟡 **Al Jazeera**"),
    ("Thairath (Thai News)", "🟢 **Thairath**"),
    ("Blognone (IT News)", "🌐 **Blognone**"),
    ("The Standard (Thai News)", "⚫ **The Standard**"),
    ("Krungthep Turakij (Business News)", "🔵 **Krungthep Turakij**"),
    ("Spaceth.co (Space News)", "🚀 **Spaceth.co**"),
    ("Physics.org (Science News)", "🔬 **Phys.org**"),
    ("Space.com (Space News)", "🌌 **Space.com**")
]

col_sel, col_clr = st.sidebar.columns(2)
if col_sel.button("Select All", use_container_width=True):
    for internal_name, _ in sources_data:
        st.session_state[f"cb_{internal_name}"] = True
    st.rerun()
if col_clr.button("Clear All", use_container_width=True):
    for internal_name, _ in sources_data:
        st.session_state[f"cb_{internal_name}"] = False
    st.rerun()
    
selected_sources = []
for internal_name, display_name in sources_data:
    key = f"cb_{internal_name}"
    if key not in st.session_state:
        st.session_state[key] = True # Default to True
        
    if st.sidebar.checkbox(display_name, key=key):
        selected_sources.append(internal_name)

if 'running_state' not in st.session_state:
    # Restore from file in case of page reload
    try:
        file_path = os.path.join(os.path.dirname(__file__), 'running_state.txt')
        with open(file_path, 'r') as f:
            st.session_state.running_state = f.read().strip() == 'True'
    except:
        st.session_state.running_state = False
    # If restored as running, fetch data again (session_state was cleared by reload)
    if st.session_state.running_state and not st.session_state.get('fetched_items'):
        all_internal_names = [src[0] for src in sources_data]
        fetch_all_data(all_internal_names)

# Custom styled START/STOP button
if st.session_state.running_state:
    clicked = st.sidebar.button("⏹ STOP", use_container_width=True, type="primary")
else:
    clicked = st.sidebar.button("▶ START", use_container_width=True, type="primary")

if clicked:
    st.session_state.running_state = not st.session_state.running_state
    # Persist to file so page reloads don't reset state
    try:
        file_path = os.path.join(os.path.dirname(__file__), 'running_state.txt')
        with open(file_path, 'w') as f:
            f.write(str(st.session_state.running_state))
    except:
        pass
    if st.session_state.running_state:
        # Starting: fetch ALL sources and enable background thread
        BG_CONFIG["running"] = True
        all_internal_names = [src[0] for src in sources_data]
        fetch_all_data(all_internal_names)
    else:
        # Stopping: disable background thread and clear displayed data
        BG_CONFIG["running"] = False
        BG_CONFIG["interval_minutes"] = 0
        st.session_state.fetched_items = []
    st.rerun()

# Dynamic button color based on state
btn_bg = "#00CC44" if st.session_state.running_state else "#CC0000"
st.sidebar.markdown(f"""
<style>
    [data-testid="stSidebar"] button[kind="primary"] {{
        background-color: {btn_bg} !important;
        color: white !important;
    }}
    [data-testid="stSidebar"] button[kind="primary"]:hover {{
        background-color: {btn_bg} !important;
        opacity: 0.85;
    }}
</style>
""", unsafe_allow_html=True)

st.sidebar.subheader("🔄 Auto Refresh")
enable_auto = st.sidebar.toggle("Enable Background Fetching", value=True)

if enable_auto:
    auto_refresh_interval = st.sidebar.slider("Interval (Minutes)", min_value=1, max_value=60, value=5)
else:
    auto_refresh_interval = 0

# --- Timezone Selector ---
st.sidebar.subheader("🌐 Timezone")
TIMEZONE_OPTIONS = {
    "UTC-12:00 (Baker Island)": -12,
    "UTC-11:00 (Samoa)": -11,
    "UTC-10:00 (Hawaii)": -10,
    "UTC-09:00 (Alaska)": -9,
    "UTC-08:00 (Pacific US)": -8,
    "UTC-07:00 (Mountain US)": -7,
    "UTC-06:00 (Central US)": -6,
    "UTC-05:00 (Eastern US)": -5,
    "UTC-04:00 (Atlantic)": -4,
    "UTC-03:00 (Buenos Aires)": -3,
    "UTC-02:00 (Mid-Atlantic)": -2,
    "UTC-01:00 (Azores)": -1,
    "UTC+00:00 (London/GMT)": 0,
    "UTC+01:00 (Paris/Berlin)": 1,
    "UTC+02:00 (Cairo/Helsinki)": 2,
    "UTC+03:00 (Moscow/Riyadh)": 3,
    "UTC+03:30 (Tehran)": 3.5,
    "UTC+04:00 (Dubai)": 4,
    "UTC+05:00 (Karachi)": 5,
    "UTC+05:30 (India/IST)": 5.5,
    "UTC+05:45 (Nepal)": 5.75,
    "UTC+06:00 (Dhaka)": 6,
    "UTC+06:30 (Myanmar)": 6.5,
    "UTC+07:00 (Bangkok/Jakarta)": 7,
    "UTC+08:00 (Singapore/HK)": 8,
    "UTC+09:00 (Tokyo/Seoul)": 9,
    "UTC+09:30 (Adelaide)": 9.5,
    "UTC+10:00 (Sydney)": 10,
    "UTC+11:00 (Vladivostok)": 11,
    "UTC+12:00 (Auckland)": 12,
    "UTC+13:00 (Samoa)": 13,
}
tz_names = list(TIMEZONE_OPTIONS.keys())
# Default to UTC+07:00 (Bangkok)
default_tz_idx = tz_names.index("UTC+07:00 (Bangkok/Jakarta)")
selected_tz_name = st.sidebar.selectbox("เลือก Timezone ของคุณ", tz_names, index=default_tz_idx, key="user_timezone")
user_utc_offset_hours = TIMEZONE_OPTIONS[selected_tz_name]
user_tz = timezone(timedelta(hours=user_utc_offset_hours))

def format_ts(ts):
    """Format a Unix timestamp to HH:MM:SS in the user's selected timezone."""
    if ts <= 0:
        return "--:--:--"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(user_tz)
    return dt.strftime("%H:%M:%S")

# Update background config safely — only set interval when running
if st.session_state.get('running_state', False):
    BG_CONFIG["interval_minutes"] = auto_refresh_interval
    BG_CONFIG["running"] = True
else:
    BG_CONFIG["interval_minutes"] = 0
    BG_CONFIG["running"] = False
BG_CONFIG["sources"] = selected_sources

# --- Show Refresh Status ---
if enable_auto and auto_refresh_interval > 0 and st.session_state.get('running_state', False):
    import time as time_mod
    last_fetch = st.session_state.get('last_fetch_time', 0)
    # Check file — if bg thread fetched new data, auto-rerun to update display
    try:
        file_path = os.path.join(os.path.dirname(__file__), 'last_fetch.txt')
        with open(file_path, 'r') as f:
            file_ts = float(f.read().strip())
            if file_ts > last_fetch:
                st.session_state['last_fetch_time'] = file_ts  # update first to avoid loop
                st.rerun()  # then rerun to refresh display
    except:
        pass
    last_fetch = st.session_state.get('last_fetch_time', 0)

    now = time_mod.time()
    last_time_str = format_ts(last_fetch)

    if last_fetch > 0:
        next_fetch_ts = last_fetch + auto_refresh_interval * 60
        next_time_str = format_ts(next_fetch_ts)
        interval_ms = auto_refresh_interval * 60 * 1000
        fetch_ts_ms = int(last_fetch * 1000)
    else:
        next_time_str = "--:--:--"
        interval_ms = 0
        fetch_ts_ms = 0

    with st.sidebar:
        components.html(f"""
        <div style='background:rgba(255,255,255,0.08);border-radius:8px;padding:10px;font-size:12px;font-family:sans-serif;'>
            <div style='color:#aaa;'>📡 กวาดข่าวล่าสุด: <b style='color:white'>{last_time_str}</b></div>
            <div style='color:#aaa;margin-top:4px;'>🔜 ครั้งถัดไปเวลา: <b style='color:white'>{next_time_str}</b></div>
            <div id='cd' style='font-weight:bold;font-size:16px;margin-top:4px;color:#00CC44;'>--:--</div>
        </div>
        <script>
        if (window.__cdInterval) clearInterval(window.__cdInterval);
        const fetchTs = {fetch_ts_ms};
        const intervalMs = {interval_ms};
        let reloaded = false;
        function tick() {{
            const el = document.getElementById('cd');
            if (!el) return;
            if (fetchTs === 0 || intervalMs === 0) {{
                el.textContent = '⏳ ยังไม่ได้กวาดข่าว';
                el.style.color = '#aaa';
                return;
            }}
            const remaining = Math.max(0, intervalMs - (Date.now() - fetchTs));
            const mins = String(Math.floor(remaining / 60000)).padStart(2,'0');
            const secs = String(Math.floor((remaining % 60000) / 1000)).padStart(2,'0');
            el.textContent = (remaining <= 30000 ? '⚡ ' : '✅ ') + mins + ':' + secs;
            el.style.color = remaining <= 30000 ? '#FF6B35' : '#00CC44';
            // Auto-reload page when countdown hits 0 so Streamlit picks up new fetch time
            if (remaining === 0 && !reloaded) {{
                reloaded = true;
                el.textContent = '🔄 กำลังอัปเดต...';
                setTimeout(() => window.top.location.reload(), 2000);
            }}
        }}
        tick();
        window.__cdInterval = setInterval(tick, 1000);
        </script>
        """, height=105)

st.sidebar.markdown("---")
st.sidebar.markdown("<div style='text-align: center; color: #bbb; font-size: 15px;'>Credits: <b style='color: white;'>Joopiest Udomsaph</b></div>", unsafe_allow_html=True)


# --- Main Feed ---

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;700&display=swap');
    body, .stApp, p, div, h1, h2, h3 {
        font-family: 'Sarabun', sans-serif !important;
    }
    span:not([class*="icon"]):not([data-testid*="Icon"]):not(.material-symbols-rounded):not(.material-icons) {
        font-family: 'Sarabun', sans-serif !important;
    }
    /* Navigation bar: neat multi-row with spacing */
    [data-testid="stRadio"] > div {
        flex-wrap: wrap !important;
        gap: 6px 8px !important;
    }
    [data-testid="stRadio"] > div > label {
        font-size: 13px !important;
        padding: 4px 10px !important;
        white-space: nowrap !important;
        margin-bottom: 6px !important;
    }
    /* START button: red, STOP button: green */
    [data-testid="stSidebar"] button[kind="primary"] {
        border: none !important;
        font-weight: bold !important;
        font-size: 16px !important;
        padding: 12px !important;
        border-radius: 8px !important;
    }
    .news-card {
        background: rgba(255, 255, 255, 0.02);
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 12px;
        border: 1px solid rgba(255, 255, 255, 0.05);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .news-card:hover {
        background: rgba(255, 255, 255, 0.05);
        transform: translateY(-2px);
        border-color: rgba(255, 255, 255, 0.1);
        box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    }
    .source-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: bold;
        text-transform: uppercase;
        margin-right: 10px;
        color: white;
    }
    .category-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 6px;
        font-size: 11px;
        background: rgba(255, 255, 255, 0.08);
        color: #AAA;
        font-weight: 500;
    }
    .news-title {
        font-size: 16px;
        font-weight: 600;
        color: #FFF;
        text-decoration: none;
        display: block;
        margin-top: 8px;
    }
    .news-title:hover {
        color: #4285F4 !important;
    }
    .score-box {
        font-size: 18px;
        font-weight: 800;
        text-align: center;
        min-width: 40px;
    }
    /* Hide default Streamlit button borders for a cleaner look */
    .stButton > button {
        border: none !important;
        background: transparent !important;
        font-size: 20px !important;
        padding: 0 !important;
        color: #666 !important;
        height: auto !important;
        line-height: 1 !important;
    }
    .stButton > button:hover {
        color: #FFF !important;
        background: transparent !important;
    }
</style>
""", unsafe_allow_html=True)

if not st.session_state.fetched_items:
    st.info("Feed is empty. Click 'Refresh Feed' in the sidebar to load the latest trends!")
else:
    # Calculate Total Score and Sort
    def get_total_score(item):
        user_vote = st.session_state.user_votes.get(item['id'], 0)
        # We multiply user vote by a large weight (e.g. 1000) so that local clicks 
        # have an immediate and noticeable impact on sorting against large base scores.
        return item['base_score'] + (user_vote * 5000)

    # Mapping from UI options to internal source names
    SOURCE_MAPPING = {
        "Reddit (Global Trends)": "Reddit",
        "Pantip (Thai Trends)": "Pantip",
        "Google News (Thailand)": "Google News TH",
        "Google News TH (IT)": "Google News TH (IT)",
        "BBC (Global News)": "BBC News",
        "CNN (Global News)": "CNN",
        "Al Jazeera (Global News)": "Al Jazeera",
        "Thairath (Thai News)": "Thairath",
        "Blognone (IT News)": "Blognone",
        "The Standard (Thai News)": "The Standard",
        "Krungthep Turakij (Business News)": "Krungthep Turakij",
        "Spaceth.co (Space News)": "Spaceth.co",
        "Physics.org (Science News)": "Phys.org",
        "Space.com (Space News)": "Space.com"
    }
    
    # Mapping from UI options to internal source names
    allowed_names = [SOURCE_MAPPING.get(src, src) for src in selected_sources]
    
    # Filter items by selected sources
    filtered_items = [item for item in st.session_state.fetched_items if item['source'] in allowed_names]
    if search_query:
        filtered_items = [item for item in filtered_items if search_query.lower() in item['title'].lower()]
    
    # Save to file for API server (handles thread reload issues)
    import json
    import os
    file_path = r'd:\JoopFirebase\Digg Like\current_feed.json'
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(filtered_items, f, ensure_ascii=False)

    # Sort filtered items by computed total score
    sorted_items = sorted(filtered_items, key=get_total_score, reverse=True)

    # Helper to render a single item
    def render_item(item, tab_prefix):
        total_score = get_total_score(item)
        item_id = item['id']
        current_vote = st.session_state.user_votes.get(item_id, 0)
        
        # Columns layout for each post (adjusted for 3-column page layout)
        col_vote, col_content = st.columns([2.5, 7.5])
        
        with col_vote:
            st.markdown("<div style='height: 5px'></div>", unsafe_allow_html=True)
            
            # Digg Button
            up_color = "#FF4500" if current_vote > 0 else "#666"
            if st.button("▲", key=f"up_{item_id}_{tab_prefix}"):
                st.session_state.user_votes[item_id] = 1 if current_vote <= 0 else 0
                st.rerun()
                
            # Score
            st.markdown(f"<div class='score-box' style='color: {'#ff4500' if total_score > item['base_score'] else '#888'};'>{total_score}</div>", unsafe_allow_html=True)
            
            # Bury Button
            down_color = "#4285F4" if current_vote < 0 else "#666"
            if st.button("▼", key=f"down_{item_id}_{tab_prefix}"):
                st.session_state.user_votes[item_id] = -1 if current_vote >= 0 else 0
                st.rerun()

        with col_content:
            source_colors = {
                "Reddit": "#FF4500",
                "Pantip": "#3f3652",
                "Google News TH": "#4285F4",
                "Google News TH (IT)": "#FBBC05",
                "BBC News": "#B80000",
                "CNN": "#CC0000",
                "Al Jazeera": "#FF9900",
                "Thairath": "#009944",
                "Blognone": "#005588",
                "The Standard": "#000000",
                "Krungthep Turakij": "#003366",
                "Spaceth.co": "#0A0E17",
                "Phys.org": "#2B4C7E",
                "Space.com": "#00518A"
            }
            bg_color = source_colors.get(item['source'], "#444")
            
            st.markdown(f"""
            <div class="news-card">
                <div style="flex: 1;">
                    <span class="source-badge" style="background-color: {bg_color};">{item['source']}</span>
                    <span class="category-badge">{item['category']}</span>
                    <a class="news-title" href="{item['url']}" target="_blank">{item['title']}</a>
                </div>
            </div>
            """, unsafe_allow_html=True)

    # Use fixed categories to avoid tab jumping when sources change
    fixed_categories = ["ข่าวด่วน (Breaking)", "เทคโนโลยี (Tech)", "การศึกษา (Education)", "การเมือง (Politics)", "การเงิน (Finance)", "เศรษฐกิจ (Economy)", "บันเทิง (Entertainment)", "ทั่วไป (General)"]
    
    # Create Navigation Bar (using radio for state persistence)
    tab_options = ["📊 Digg Stack", "All Feed"] + fixed_categories
    active_tab = st.radio("Navigation", tab_options, horizontal=True, label_visibility="collapsed")
    
    # "All" Tab
    if active_tab == "All Feed":
        cols = st.columns(3)
        for idx, item in enumerate(sorted_items):
            with cols[idx % 3]:
                render_item(item, f"all_{idx}")
            
    for i, category in enumerate(fixed_categories):
        if active_tab == category:
            cat_items = [item for item in sorted_items if item['category'] == category]
            cols = st.columns(3)
            for idx, item in enumerate(cat_items):
                with cols[idx % 3]:
                    render_item(item, f"cat_{i}_{idx}")

    # "Digg Stack" Visualizer Tab
    if active_tab == "📊 Digg Stack":
        st.markdown("### Real-time Falling Block Visualization")
        
        import time as time_mod
        last_fetch_ts = st.session_state.get('last_fetch_time', 0)
        fetch_time_str = format_ts(last_fetch_ts)
        stack_data = [{"id": item['id'], "title": item['title'], "category": item['category'], "score": get_total_score(item), "url": item['url'], "source": item['source'], "fetch_time": fetch_time_str} for item in sorted_items]
        js_data = json.dumps(stack_data)
        
        html_code = """
        <!-- FORCE RELOAD V2 -->
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { margin: 0; background-color: #1E1E1E; color: white; font-family: sans-serif; overflow: hidden; }
                canvas { display: block; width: 100%; height: 600px; }
            </style>
        </head>
        <body>
            <canvas id="diggCanvas"></canvas>
            <script>
                const canvas = document.getElementById('diggCanvas');
                const ctx = canvas.getContext('2d');
                
                // Ensure canvas matches iframe size
                canvas.width = window.innerWidth;
                canvas.height = 600; 
                let rawData = []; // Populated by Python
                
                const CATEGORIES = ["ข่าวด่วน (Breaking)", "เทคโนโลยี (Tech)", "การศึกษา (Education)", "การเมือง (Politics)", "การเงิน (Finance)", "เศรษฐกิจ (Economy)", "บันเทิง (Entertainment)", "ทั่วไป (General)"];
                const COLORS = {
                    "Reddit": "#FF4500",
                    "Pantip": "#3f3652",
                    "Google News TH": "#4285F4",
                    "Google News TH (IT)": "#FBBC05",
                    "BBC News": "#B80000",
                    "CNN": "#CC0000",
                    "Al Jazeera": "#FF9900",
                    "Thairath": "#009944",
                    "Blognone": "#005588",
                    "The Standard": "#000000",
                    "Krungthep Turakij": "#003366",
                    "Spaceth.co": "#0A0E17",
                    "Phys.org": "#2B4C7E",
                    "Space.com": "#00518A"
                };
                
                let blocks = [];
                let queue = [...rawData];
                let columnHeights = [];
                let initialized = false;
                
                // Camera variables (Independent per column)
                let cameraY = [];
                let targetCameraY = [];
                let hoveredCol = -1;
                
                class Block {
                    constructor(data, colWidth, floorY) {
                        this.data = data;
                        this.category = data.category;
                        this.source = data.source || "Unknown";
                        
                        let catIdx = CATEGORIES.indexOf(this.category);
                        if(catIdx === -1) catIdx = CATEGORIES.length - 1;
                        
                        this.col = catIdx;
                        this.color = COLORS[this.source] || "#95a5a6";
                        
                        let score = data.base_score || data.score || 100;
                        this.height = Math.max(25, Math.min(150, Math.floor(score / 100)));
                        this.width = colWidth - 10;
                        
                        // Start off screen (above camera for its specific column)
                        this.x = this.col * colWidth + 5;
                        this.y = -this.height - Math.max(0, cameraY[this.col] || 0); 
                        
                        this.targetY = columnHeights[this.col] - this.height;
                        columnHeights[this.col] = this.targetY;
                        
                        this.speedY = 7;
                        this.stopped = false;
                    }
                    
                    update() {
                        if (!this.stopped) {
                            this.y += this.speedY;
                            if (this.y >= this.targetY) {
                                this.y = this.targetY;
                                this.stopped = true;
                            }
                        }
                    }
                    
                    draw() {
                        let currentCamY = cameraY[this.col] || 0;
                        let drawY = this.y + currentCamY;
                        
                        // 1. Base Shape with Shadow
                        ctx.save();
                        ctx.shadowColor = "rgba(0, 0, 0, 0.4)";
                        ctx.shadowBlur = 8;
                        ctx.shadowOffsetY = 4;
                        
                        ctx.fillStyle = this.color;
                        ctx.beginPath();
                        if (ctx.roundRect) {
                            ctx.roundRect(this.x, drawY, this.width, this.height, 6);
                        } else {
                            ctx.rect(this.x, drawY, this.width, this.height);
                        }
                        ctx.fill();
                        ctx.restore(); // Remove shadow
                        
                        // 2. Glossy/Volume Gradient (Light effect)
                        let grad = ctx.createLinearGradient(this.x, drawY, this.x, drawY + this.height);
                        grad.addColorStop(0, "rgba(255, 255, 255, 0.25)");
                        grad.addColorStop(0.3, "rgba(255, 255, 255, 0.05)");
                        grad.addColorStop(0.7, "rgba(0, 0, 0, 0.05)");
                        grad.addColorStop(1, "rgba(0, 0, 0, 0.35)");
                        
                        ctx.fillStyle = grad;
                        ctx.beginPath();
                        if (ctx.roundRect) {
                            ctx.roundRect(this.x, drawY, this.width, this.height, 6);
                        } else {
                            ctx.rect(this.x, drawY, this.width, this.height);
                        }
                        ctx.fill();
                        
                        // 3. Top Inner Highlight (Bevel)
                        ctx.strokeStyle = "rgba(255, 255, 255, 0.4)";
                        ctx.lineWidth = 1;
                        ctx.beginPath();
                        ctx.moveTo(this.x + 6, drawY + 1);
                        ctx.lineTo(this.x + this.width - 6, drawY + 1);
                        ctx.stroke();
                        
                        // 4. Subtle Border
                        ctx.strokeStyle = "rgba(255, 255, 255, 0.2)";
                        ctx.lineWidth = 1;
                        ctx.beginPath();
                        if (ctx.roundRect) {
                            ctx.roundRect(this.x, drawY, this.width, this.height, 6);
                        } else {
                            ctx.rect(this.x, drawY, this.width, this.height);
                        }
                        ctx.stroke();
                        
                        // Text Rendering
                        ctx.fillStyle = "white";
                        ctx.font = "bold 12px sans-serif";
                        ctx.textBaseline = "middle";
                        ctx.textAlign = "center";
                        
                        let maxChars = Math.max(2, Math.floor(this.width / 8));
                        let title = this.data.title;
                        if(title.length > maxChars) {
                            title = title.substring(0, maxChars) + "..";
                        }
                        
                        ctx.save();
                        ctx.beginPath();
                        if (ctx.roundRect) {
                            ctx.roundRect(this.x, drawY, this.width, this.height, 6);
                        } else {
                            ctx.rect(this.x, drawY, this.width, this.height);
                        }
                        ctx.clip();
                        
                        let scoreVal = this.data.base_score || this.data.score || 100;
                        if (this.height > 60) {
                            // Draw title a bit higher
                            ctx.font = "bold 12px sans-serif";
                            ctx.fillText(title, this.x + this.width/2, drawY + this.height/2 - 10);
                            
                            // Draw score and time below
                            ctx.font = "bold 10px sans-serif";
                            ctx.fillStyle = "rgba(255, 255, 255, 0.8)";
                            let timeStr = this.data.fetch_time || "--:--";
                            ctx.fillText("🔥 " + scoreVal.toLocaleString() + "  |  🕒 " + timeStr, this.x + this.width/2, drawY + this.height/2 + 10);
                        } else {
                            // Draw title centered
                            ctx.font = "bold 12px sans-serif";
                            ctx.fillText(title, this.x + this.width/2, drawY + this.height/2);
                        }
                        
                        ctx.restore();
                    }
                }
                
                function spawnBlock() {
                    if (initialized && queue.length > 0) {
                        let COL_WIDTH = canvas.width / CATEGORIES.length;
                        let FLOOR_Y = canvas.height - 40;
                        let block = new Block(queue.shift(), COL_WIDTH, FLOOR_Y);
                        blocks.push(block);
                        
                        let col = block.col;
                        // Calculate max scroll needed to keep the top of the stack visible at y = 100
                        let maxScroll = Math.max(0, 100 - columnHeights[col]);
                        
                        // Auto pan only if the stack is actually going off screen
                        if (columnHeights[col] < 100) {
                            if (targetCameraY[col] >= maxScroll - 200) {
                                targetCameraY[col] = maxScroll;
                            }
                        } else {
                            targetCameraY[col] = 0; // Keep bottom blocks on the floor
                        }
                    }
                }
                
                async function init() {
                    if (canvas.height === 0) {
                        setTimeout(init, 100);
                        return;
                    }
                    
                    let COLUMNS = CATEGORIES.length;
                    let FLOOR_Y = canvas.height - 40;
                    columnHeights = new Array(COLUMNS).fill(FLOOR_Y);
                    cameraY = new Array(COLUMNS).fill(0);
                    targetCameraY = new Array(COLUMNS).fill(0);
                    
                    // Data is injected directly from Python, no fetch needed
                    
                    queue = [...rawData];
                    
                    initialized = true;
                }
                init();
                
                setInterval(spawnBlock, 600);
                
                // Polling removed for Streamlit Cloud compatibility
                
                // --- Interaction System ---
                canvas.addEventListener('wheel', (e) => {
                    if (initialized && hoveredCol !== -1) {
                        e.preventDefault(); // Prevent parent page from scrolling
                        targetCameraY[hoveredCol] += e.deltaY * 0.5; // Scale scroll speed
                        
                        let maxScroll = Math.max(0, 100 - columnHeights[hoveredCol]);
                        if (targetCameraY[hoveredCol] < 0) targetCameraY[hoveredCol] = 0;
                        if (targetCameraY[hoveredCol] > maxScroll) targetCameraY[hoveredCol] = maxScroll;
                    }
                }, { passive: false });
                
                let hoveredBlockUrl = null;
                let hoveredBlockSource = null;
                let hoveredBlockTitle = null;
                let hoveredBlockFetchTime = null;
                let mouseX = 0;
                let mouseY = 0;
                
                canvas.addEventListener('mousemove', (e) => {
                    const rect = canvas.getBoundingClientRect();
                    mouseX = e.clientX - rect.left;
                    mouseY = e.clientY - rect.top;
                    
                    hoveredBlockUrl = null;
                    hoveredBlockSource = null;
                    hoveredBlockTitle = null;
                    hoveredBlockFetchTime = null;
                    hoveredCol = -1;
                    canvas.style.cursor = 'default';
                    
                    // Calculate which column we are hovering
                    if (initialized) {
                        let COL_WIDTH = canvas.width / CATEGORIES.length;
                        hoveredCol = Math.floor(mouseX / COL_WIDTH);
                        if (hoveredCol >= CATEGORIES.length) hoveredCol = CATEGORIES.length - 1;
                        if (hoveredCol < 0) hoveredCol = 0;
                    }
                    
                    // Don't hover block if mouse is over the sticky footer
                    if (mouseY > canvas.height - 40) return;
                    
                    for (let block of blocks) {
                        let currentCamY = cameraY[block.col] || 0;
                        let worldY = mouseY - currentCamY;
                        
                        if (mouseX >= block.x && mouseX <= block.x + block.width &&
                            worldY >= block.y && worldY <= block.y + block.height) {
                            hoveredBlockUrl = block.data.url;
                            hoveredBlockSource = block.source;
                            hoveredBlockTitle = block.data.title;
                            hoveredBlockFetchTime = block.data.fetch_time || '--:--:--';
                            canvas.style.cursor = 'pointer';
                            break;
                        }
                    }
                });
                
                canvas.addEventListener('click', () => {
                    if (hoveredBlockUrl) {
                        window.open(hoveredBlockUrl, '_blank');
                    } else if (hoveredCol !== -1 && mouseY > canvas.height - 40) {
                        // Clicked on the footer/label of a column!
                        // Toggle between viewing the top and bottom
                        let maxScroll = Math.max(0, 100 - columnHeights[hoveredCol]);
                        if (targetCameraY[hoveredCol] > maxScroll / 2) {
                            targetCameraY[hoveredCol] = 0; // Snap to bottom
                        } else {
                            targetCameraY[hoveredCol] = maxScroll; // Snap to top
                        }
                    }
                });
                
                function animate() {
                    ctx.fillStyle = "#1E1E1E";
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                    
                    let COLUMNS = CATEGORIES.length;
                    let COL_WIDTH = canvas.width / COLUMNS;
                    let FLOOR_Y = canvas.height - 40;
                    
                    if (rawData.length === 0) {
                        ctx.fillStyle = "#888";
                        ctx.font = "20px sans-serif";
                        ctx.textAlign = "center";
                        ctx.fillText("Waiting for data... Please click 'Refresh Feed' in sidebar.", canvas.width/2, canvas.height/2);
                    }
                    
                    if (initialized) {
                        for (let i = 0; i < COLUMNS; i++) {
                            // Smooth camera interpolation per column
                            cameraY[i] += (targetCameraY[i] - cameraY[i]) * 0.1;
                        }
                    }
                    
                    for (let block of blocks) {
                        block.update();
                        block.draw();
                    }
                    

                    
                    // Draw Sticky Footer (Static)
                    ctx.fillStyle = "#1E1E1E";
                    ctx.fillRect(0, FLOOR_Y, canvas.width, canvas.height - FLOOR_Y);
                    
                    ctx.strokeStyle = "#555";
                    ctx.lineWidth = 2;
                    ctx.beginPath();
                    ctx.moveTo(0, FLOOR_Y);
                    ctx.lineTo(canvas.width, FLOOR_Y);
                    ctx.stroke();
                    
                    // Draw Labels
                    ctx.fillStyle = "#CCC";
                    ctx.font = "bold 14px sans-serif";
                    ctx.textAlign = "center";
                    ctx.textBaseline = "top";
                    for(let i=0; i<CATEGORIES.length; i++) {
                        let label = CATEGORIES[i].split(" (")[0];
                        ctx.fillText(label, i * COL_WIDTH + COL_WIDTH/2, FLOOR_Y + 10);
                    }
                    
                    // Draw Hover Tooltip (Source + Fetch Time + Full Headline)
                    if (hoveredBlockSource) {
                        ctx.font = "bold 12px sans-serif";
                        let line1 = "📰 " + hoveredBlockSource;
                        let line2 = "🕒 Fetched: " + (hoveredBlockFetchTime || '--:--:--');
                        
                        // Word-wrap the title to fit tooltip
                        ctx.font = "12px sans-serif";
                        let fullTitle = hoveredBlockTitle || '';
                        let maxTooltipW = 320;
                        let titleLines = [];
                        let words = fullTitle.split('');
                        let currentLine = '';
                        for (let ch of words) {
                            let testLine = currentLine + ch;
                            if (ctx.measureText(testLine).width > maxTooltipW - 20) {
                                titleLines.push(currentLine);
                                currentLine = ch;
                            } else {
                                currentLine = testLine;
                            }
                        }
                        if (currentLine) titleLines.push(currentLine);
                        // Limit to 4 lines max
                        if (titleLines.length > 4) {
                            titleLines = titleLines.slice(0, 4);
                            titleLines[3] = titleLines[3].substring(0, titleLines[3].length - 2) + '..';
                        }
                        
                        // Measure widths
                        ctx.font = "bold 12px sans-serif";
                        let w1 = ctx.measureText(line1).width;
                        let w2 = ctx.measureText(line2).width;
                        ctx.font = "12px sans-serif";
                        let maxTitleW = 0;
                        for (let tl of titleLines) {
                            let tw = ctx.measureText(tl).width;
                            if (tw > maxTitleW) maxTitleW = tw;
                        }
                        let tooltipW = Math.min(maxTooltipW, Math.max(w1, w2, maxTitleW) + 30);
                        let lineH = 18;
                        let tooltipH = 12 + lineH * 2 + 6 + lineH * titleLines.length + 10;
                        
                        // Position tooltip (flip if near edge)
                        let tx = mouseX + 15;
                        let ty = mouseY + 15;
                        if (tx + tooltipW > canvas.width) tx = mouseX - tooltipW - 10;
                        if (ty + tooltipH > canvas.height) ty = mouseY - tooltipH - 10;
                        
                        // Background
                        ctx.fillStyle = "rgba(0, 0, 0, 0.92)";
                        ctx.beginPath();
                        if (ctx.roundRect) {
                            ctx.roundRect(tx, ty, tooltipW, tooltipH, 8);
                        } else {
                            ctx.rect(tx, ty, tooltipW, tooltipH);
                        }
                        ctx.fill();
                        
                        // Border
                        ctx.strokeStyle = "rgba(255, 255, 255, 0.15)";
                        ctx.lineWidth = 1;
                        ctx.beginPath();
                        if (ctx.roundRect) {
                            ctx.roundRect(tx, ty, tooltipW, tooltipH, 8);
                        } else {
                            ctx.rect(tx, ty, tooltipW, tooltipH);
                        }
                        ctx.stroke();
                        
                        // Line 1: Source
                        ctx.fillStyle = "#FFD700";
                        ctx.font = "bold 12px sans-serif";
                        ctx.textAlign = "left";
                        ctx.textBaseline = "top";
                        ctx.fillText(line1, tx + 10, ty + 8);
                        
                        // Line 2: Fetch time
                        ctx.fillStyle = "#8BC34A";
                        ctx.fillText(line2, tx + 10, ty + 8 + lineH);
                        
                        // Separator line
                        ctx.strokeStyle = "rgba(255, 255, 255, 0.1)";
                        ctx.beginPath();
                        let sepY = ty + 8 + lineH * 2 + 2;
                        ctx.moveTo(tx + 10, sepY);
                        ctx.lineTo(tx + tooltipW - 10, sepY);
                        ctx.stroke();
                        
                        // Title lines
                        ctx.fillStyle = "#FFFFFF";
                        ctx.font = "12px sans-serif";
                        for (let li = 0; li < titleLines.length; li++) {
                            ctx.fillText(titleLines[li], tx + 10, sepY + 6 + li * lineH);
                        }
                    }
                    
                    requestAnimationFrame(animate);
                }
                
                animate();
            </script>
        </body>
        </html>
        """
        html_code = html_code.replace('let rawData = []; // Populated by Python', f'let rawData = {js_data};')
        components.html(html_code, height=600)
