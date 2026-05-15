import streamlit as st
from collections import Counter
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
try:
    from wordcloud import WordCloud
    import matplotlib.pyplot as plt
except ImportError:
    WordCloud = None
    import matplotlib.pyplot as plt
try:
    from pythainlp.tokenize import word_tokenize
    from pythainlp.corpus import thai_stopwords
except ImportError:
    # Fallback if libraries are not installed yet
    word_tokenize = lambda x: x.split()
    thai_stopwords = lambda: set()

# --- Firebase Initialization ---
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    try:
        # Try local JSON file first (Parent directory)
        cred_path = os.path.join(os.path.dirname(__file__), '..', 'joopiest-f16cf-firebase-adminsdk-fbsvc-3547a4eba1.json')
        
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        else:
            # Try Streamlit Secrets (Cloud)
            try:
                if "firebase" in st.secrets:
                    cert_dict = dict(st.secrets["firebase"])
                    cred = credentials.Certificate(cert_dict)
                    firebase_admin.initialize_app(cred)
                else:
                    st.warning("Firebase credentials not found (No JSON or Secrets). Global voting disabled.")
            except:
                # Handle cases where st.secrets is accessed but no secrets.toml exists
                st.warning("Firebase credentials not found (Local Mode). Global voting disabled.")
    except Exception as e:
        st.error(f"Error initializing Firebase: {e}")

try:
    db = firestore.client()
except:
    db = None

def update_global_vote(item_id, old_vote, new_vote):
    diff = (new_vote - old_vote) * 5000
    if diff != 0 and db:
        try:
            doc_ref = db.collection('app_state').document('global_votes')
            doc_ref.set({item_id: firestore.Increment(diff)}, merge=True)
        except Exception as e:
            st.error(f"Error updating global vote: {e}")

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
    /* Import Premium Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=Sarabun:wght@300;400;700&display=swap');

    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Inter', 'Sarabun', sans-serif !important;
        background-color: #0F172A !important; /* Deeper Dark Blue */
    }

    .post-container {
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 20px;
        background: rgba(255, 255, 255, 0.03);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        display: flex;
        flex-direction: row;
        align-items: flex-start;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .post-container:hover {
        background: rgba(255, 255, 255, 0.06);
        border-color: rgba(255, 255, 255, 0.2);
        transform: translateY(-4px);
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
    }
    .score-box {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        width: 80px;
        margin-right: 20px;
        background: rgba(255, 255, 255, 0.05);
        border-radius: 12px;
        padding: 10px;
    }
    .score-number {
        font-size: 26px;
        font-weight: 800;
        background: linear-gradient(135deg, #FF6B35, #FF4500);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 5px 0;
    }
    .post-content {
        flex-grow: 1;
    }
    .post-title {
        font-size: 20px;
        font-weight: 700;
        color: #F8FAFC;
        text-decoration: none;
        line-height: 1.4;
    }
    .post-source {
        font-size: 14px;
        color: #94A3B8;
        margin-top: 8px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .tag {
        background: rgba(255, 255, 255, 0.1);
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 12px;
        color: #CBD5E1;
        font-weight: 600;
        border: 1px solid rgba(255, 255, 255, 0.05);
    }
    </style>
""", unsafe_allow_html=True)

# --- State Management ---
if "user_votes" not in st.session_state:
    st.session_state.user_votes = {} # dict mapping item_id -> vote modifier (+1 or -1)
if "fetched_items" not in st.session_state:
    st.session_state.fetched_items = []

# Fetch global votes on every run to get latest data
global_votes = {}
if db:
    try:
        doc_ref = db.collection('app_state').document('global_votes')
        doc = doc_ref.get()
        if doc.exists:
            global_votes = doc.to_dict()
    except Exception as e:
        pass

# --- Data Fetching Functions ---
import re

def assign_topic_category(text_to_search, fallback_category):
    text_lower = text_to_search.lower()
    
    # Category definition with both English (regex-ready) and Thai keywords
    # Order matters: more specific categories should come before general ones
    keywords = {
        "Breaking": {
            "en": [r'breaking', r'urgent', r'alert', r'crisis', r'latest', r'just in', r'live'],
            "th": ['ด่วน', 'ข่าวด่วน', 'อัปเดต', 'ประกาศสำคัญ', 'เกาะติด']
        },
        "Technology": {
            "en": [r'tech', r'technology', r'smartphone', r'software', r'hardware', r'ai', r'cyber', r'robot', r'apple', r'google', r'microsoft', r'tesla', r'nvidia', r'semiconductor', r'quantum', r'startup', r'innovation'],
            "th": ['มือถือ', 'ไอที', 'คอมพิวเตอร์', 'หุ่นยนต์', 'สมาร์ทโฟน', 'แอพ', 'แอป', 'เทคโนโลยี', 'อวกาศ', 'นวัตกรรม', 'ยานยนต์ไฟฟ้า', 'อีวี', 'ปัญญาประดิษฐ์']
        },
        "Economy": {
            "en": [r'economy', r'economic', r'gdp', r'inflation', r'trade', r'export', r'import', r'recession', r'tax', r'budget', r'tariff', r'fiscal', r'monetary'],
            "th": ['เศรษฐกิจ', 'ส่งออก', 'เงินเฟ้อ', 'จีดีพี', 'ภาษี', 'พาณิชย์', 'งบประมาณ', 'ดุลการค้า', 'ค่าเงิน']
        },
        "Finance": {
            "en": [r'finance', r'bank', r'stock', r'crypto', r'investment', r'market', r'bitcoin', r'btc', r'eth', r'nasdaq', r'gold', r'dividend', r'portfolio', r'forex', r'insurance'],
            "th": ['หุ้น', 'การเงิน', 'ธนาคาร', 'คริปโต', 'บิทคอยน์', 'ทองคำ', 'ดอกเบี้ย', 'เงินฝาก', 'เซต', 'set', 'ปันผล', 'ลงทุน', 'กองทุน']
        },
        "Education": {
            "en": [r'education', r'university', r'school', r'student', r'teacher', r'college', r'exam', r'scholarship', r'learning', r'academic', r'curriculum', r'literacy'],
            "th": ['การศึกษา', 'นักเรียน', 'นักศึกษา', 'มหาวิทยาลัย', 'โรงเรียน', 'สอบ', 'ทุนการศึกษา', 'เรียนต่อ', 'วิชาการ', 'ครู', 'หลักสูตร']
        },
        "Entertainment": {
            "en": [r'entertainment', r'movie', r'music', r'celebrity', r'hollywood', r'netflix', r'kpop', r'anime', r'gaming', r'esports', r'drama', r'showbiz', r'streaming', r'concert'],
            "th": ['บันเทิง', 'ภาพยนตร์', 'หนัง', 'เพลง', 'ดารา', 'ซีรีส์', 'คอนเสิร์ต', 'เกม', 'ศิลปิน', 'ละคร', 'วงการบันเทิง', 'สตรีมมิ่ง']
        },
        "Politics": {
            "en": [r'politics', r'government', r'election', r'president', r'minister', r'parliament', r'senate', r'diplomacy', 
                   r'starmer', r'biden', r'trump', r'putin', r'zelensky', r'cabinet', r'senator', r'congress', 
                   r'white house', r'labour', r'tory', r'republican', r'democrat', r'policy', r'sanction', r'treaty', 
                   r'summit', r'war', r'military', r'pentagon', r'defense', r'nato', r'un', r'asean', r'missile', 
                   r'nuclear', r'iran', r'israel', r'gaza', r'hamas', r'hezbollah', r'ukraine', r'russia', r'china', 
                   r'taiwan', r'irgc', r'cia', r'fbi', r'protest', r'veto', r'legal', r'court'],
            "th": ['การเมือง', 'เลือกตั้ง', 'รัฐบาล', 'นายก', 'สภา', 'ประท้วง', 'พรรค', 'ครม', 'รัฐมนตรี', 'ทักษิณ', 
                   'ปชน', 'ปชป', 'ก้าวไกล', 'เพื่อไทย', 'ภูมิใจไทย', 'พลังประชารัฐ', 'ม็อบ', 'ชุมนุม', 'กฎหมาย', 
                   'รัฐธรรมนูญ', 'ส.ส.', 'ส.ว.', 'วุฒิสภา', 'กกต', 'ปปช', 'ศาลรัฐธรรมนูญ', 'พ.ร.บ.', 'พ.ร.ก.', 
                   'กม.', 'สงคราม', 'ทหาร', 'กลาโหม', 'ความมั่นคง', 'อาวุธ', 'อิหร่าน', 'อิสราเอล', 'ยูเครน', 
                   'รัสเซีย', 'จีน', 'ไต้หวัน', 'พรรคร่วม', 'ปรับครม']
        },
        "General": {
            "en": [r'news', r'general', r'world', r'local', r'society', r'culture', r'lifestyle', r'health', r'environment', r'weather', r'travel'],
            "th": ['ทั่วไป', 'สังคม', 'วัฒนธรรม', 'ชาวบ้าน', 'สรุป', 'รอบวัน', 'รอบโลก', 'สุขภาพ', 'สิ่งแวดล้อม', 'สภาพอากาศ', 'ท่องเที่ยว']
        }
    }
    
    import re
    for category, langs in keywords.items():
        # 1. Check English keywords with word boundaries (\b)
        for en_word in langs["en"]:
            if re.search(rf'\b{en_word}\b', text_lower):
                return category
        
        # 2. Check Thai keywords (normal substring match since Thai doesn't use spaces)
        for th_word in langs["th"]:
            if th_word in text_lower:
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
                "category": assign_topic_category(search_text, "General")
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
                    "category": assign_topic_category(title, "General")
                })
                added_urls.add(href)
            if len(items) >= 10:
                break
        return items
    except Exception as e:
        return []

def get_raw_data(sources_selected):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    all_items = []
    
    # Mapping of source names to their fetch configurations
    # (Source Name, Fetch Function, Args)
    fetch_configs = [
        ("Reddit (Global Trends)", fetch_reddit, ()),
        ("BBC (Global News)", fetch_rss, ("http://feeds.bbci.co.uk/news/rss.xml", "BBC News", "General")),
        ("Google News (Thailand)", fetch_rss, ("https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th", "Google News TH", "General")),
        ("Google News TH (IT)", fetch_rss, ("https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB?hl=th&gl=TH&ceid=TH:th", "Google News TH (IT)", "Technology")),
        ("Pantip (Thai Trends)", fetch_pantip, ()),
        ("CNN (Global News)", fetch_rss, ("http://rss.cnn.com/rss/edition.rss", "CNN", "General")),
        ("Al Jazeera (Global News)", fetch_rss, ("https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera", "General")),
        ("Thairath (Thai News)", fetch_rss, ("https://www.thairath.co.th/rss/news", "Thairath", "General")),
        ("Blognone (IT News)", fetch_rss, ("https://www.blognone.com/atom.xml", "Blognone", "Technology")),
        ("The Standard (Thai News)", fetch_rss, ("https://thestandard.co/feed/", "The Standard", "General")),
        ("Krungthep Turakij (Business News)", fetch_rss, ("https://www.bangkokbiznews.com/rss/news", "Krungthep Turakij", "Economy")),
        ("Spaceth.co (Space News)", fetch_rss, ("https://spaceth.co/feed/", "Spaceth.co", "Technology")),
        ("Physics.org (Science News)", fetch_rss, ("https://phys.org/rss-feed/", "Phys.org", "Technology")),
        ("Space.com (Space News)", fetch_rss, ("https://www.space.com/feeds/all", "Space.com", "Technology")),
        ("MIT Tech Review (Tech News)", fetch_rss, ("https://www.technologyreview.com/feed/", "MIT Tech Review", "Technology")),
        ("Wired Magazine (Tech News)", fetch_rss, ("https://www.wired.com/feed/rss", "Wired", "Technology")),
        ("Physics World (Science News)", fetch_rss, ("https://physicsworld.com/feed/", "Physics World", "Technology"))
    ]
    
    # Increase max_workers to 20 for true parallel execution of all sources
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_source = {
            executor.submit(func, *args): name 
            for name, func, args in fetch_configs 
            if name in sources_selected
        }
        
        for future in as_completed(future_to_source):
            try:
                # Individual source timeout of 7 seconds
                all_items.extend(future.result(timeout=7))
            except Exception as e:
                # If one source fails or times out, we continue with the others
                continue
                
    return all_items

def fetch_all_data(sources_selected):
    # Provide subtle feedback that fetching is starting
    st.toast("🔄 Fetching news from all sources...", icon="🗞️")
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
                    all_sources = [src[0] for src in sources_data]
                    new_items = get_raw_data(all_sources)
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
st.markdown("""
    <style>
    [data-testid="stTabs"] button {
        white-space: normal !important;
        overflow-wrap: break-word !important;
        height: auto !important;
        min-height: 40px !important;
    }
    </style>
    """, unsafe_allow_html=True)
st.markdown("Your curated trending feed. **Digg** what you like, **Bury** what you don't. The best content rises to the top.")

# Sidebar - Preferences
st.sidebar.header("⚙️ Your Preferences")

# Search with Clear Button
# Handle incoming query params for search (from Word Cloud click)
# Use the newer st.query_params or fallback to experimental
try:
    q_params = st.query_params
    if "search" in q_params:
        st.session_state.search_input_val = q_params["search"]
        # Do not clear immediately to ensure st.text_input picks it up
except:
    pass

if 'search_input_val' not in st.session_state:
    st.session_state.search_input_val = ""

def clear_search_query():
    st.session_state.search_input_val = ""

st.sidebar.markdown("### 🔍 Search")
col_search, col_clear = st.sidebar.columns([0.7, 0.3])
with col_search:
    search_query = st.text_input("Search News", key="search_input_val", placeholder="Type to search...", label_visibility="collapsed")
with col_clear:
    # CLEAN ALIGNMENT WITHOUT BRITTLE MARGINS
    st.markdown("""
        <style>
        /* 1. Vertically center the row content */
        [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has(input[placeholder="Type to search..."]) {
            align-items: center !important;
            gap: 0 !important;
        }

        /* 2. Style the button to match the input height and look integrated */
        [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has(input[placeholder="Type to search..."]) [data-testid="stButton"] button {
            margin-top: -15px !important;
            margin-left: 15px !important; /* Moved 20px to the right from previous -5px */
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            width: 38px !important;
            height: 38px !important;
            background: rgba(255,255,255,0.05) !important;
            border: 1px solid rgba(255,255,255,0.1) !important;
            border-radius: 8px !important;
            transition: all 0.2s ease !important;
        }
        
        [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has(input[placeholder="Type to search..."]) [data-testid="stButton"] button p {
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1 !important; 
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            color: #888 !important;
            font-size: 16px !important;
        }

        [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has(input[placeholder="Type to search..."]) [data-testid="stButton"] button:hover {
            background: rgba(255,255,255,0.12) !important;
            border-color: rgba(255,255,255,0.3) !important;
        }

        /* 3. Ensure the search input field matches the height exactly */
        div[data-testid="stSidebar"] div[data-testid="stTextInput"] input {
            height: 38px !important;
            background-color: rgba(255, 255, 255, 0.03) !important;
            border: 1px solid rgba(255, 255, 255, 0.1) !important;
            border-radius: 8px !important;
            color: white !important;
        }
        div[data-testid="stSidebar"] div[data-testid="stTextInput"] input:focus {
            border-color: #ff4500 !important;
            background-color: rgba(255, 255, 255, 0.07) !important;
        }
        </style>
    """, unsafe_allow_html=True)
    st.button("✕", help="Clear Search", on_click=clear_search_query)


sources_data = [
    ("Al Jazeera (Global News)", "🟡 **Al Jazeera**"),
    ("BBC (Global News)", "🟥 **BBC News**"),
    ("Blognone (IT News)", "🌐 **Blognone**"),
    ("CNN (Global News)", "🔴 **CNN**"),
    ("Google News (Thailand)", "🟦 **Google News TH**"),
    ("Google News TH (IT)", "🟨 **Google News TH (IT)**"),
    ("Krungthep Turakij (Business News)", "🔵 **Krungthep Turakij**"),
    ("MIT Tech Review (Tech News)", "🦾 **MIT Tech Review**"),
    ("Pantip (Thai Trends)", "🟪 **Pantip**"),
    ("Physics World (Science News)", "⚛️ **Physics World**"),
    ("Physics.org (Science News)", "🔬 **Phys.org**"),
    ("Reddit (Global Trends)", "🟧 **Reddit**"),
    ("Space.com (Space News)", "🌌 **Space.com**"),
    ("Spaceth.co (Space News)", "🚀 **Spaceth.co**"),
    ("The Standard (Thai News)", "⚫ **The Standard**"),
    ("Thairath (Thai News)", "🟢 **Thairath**"),
    ("Wired Magazine (Tech News)", "🔌 **Wired**")
]

# --- Persist selected sources ---
def save_selections(selected):
    try:
        path = os.path.join(os.path.dirname(__file__), 'selected_sources.txt')
        with open(path, 'w') as f:
            f.write(",".join(selected))
    except: pass

def load_selections():
    try:
        path = os.path.join(os.path.dirname(__file__), 'selected_sources.txt')
        if os.path.exists(path):
            with open(path, 'r') as f:
                return f.read().strip().split(",")
    except: pass
    return [src[0] for src in sources_data] # Default to ALL

# Initialize checkbox states from file if session is fresh
if 'cb_initialized' not in st.session_state:
    saved = load_selections()
    for internal_name, _ in sources_data:
        st.session_state[f"cb_{internal_name}"] = internal_name in saved
    st.session_state.cb_initialized = True

col_sel, col_clr = st.sidebar.columns(2)
if col_sel.button("Select All", use_container_width=True):
    for internal_name, _ in sources_data:
        st.session_state[f"cb_{internal_name}"] = True
    save_selections([src[0] for src in sources_data])
    st.rerun()
if col_clr.button("Clear All", use_container_width=True):
    for internal_name, _ in sources_data:
        st.session_state[f"cb_{internal_name}"] = False
    save_selections([])
    st.rerun()
    
selected_sources = []
for internal_name, display_name in sources_data:
    key = f"cb_{internal_name}"
    # Track changes to save immediately
    val = st.sidebar.checkbox(display_name, key=key)
    if val:
        selected_sources.append(internal_name)

# Detect change in selection to save to file
if 'prev_selected' not in st.session_state or set(st.session_state.prev_selected) != set(selected_sources):
    save_selections(selected_sources)
    st.session_state.prev_selected = selected_sources

if 'running_state' not in st.session_state:
    # Restore from file in case of page reload
    try:
        file_path = os.path.join(os.path.dirname(__file__), 'running_state.txt')
        with open(file_path, 'r') as f:
            st.session_state.running_state = f.read().strip() == 'True'
    except:
        st.session_state.running_state = False

    # Restore refresh interval from file
    try:
        interval_path = os.path.join(os.path.dirname(__file__), 'refresh_interval.txt')
        if os.path.exists(interval_path):
            with open(interval_path, 'r') as f:
                saved_interval = int(f.read().strip())
                st.session_state.refresh_interval_slider = saved_interval
        else:
            st.session_state.refresh_interval_slider = 5
    except:
        st.session_state.refresh_interval_slider = 5

    # If restored as running, fetch all data (UI filters display)
    if st.session_state.running_state and not st.session_state.get('fetched_items'):
        all_sources = [src[0] for src in sources_data]
        fetch_all_data(all_sources)

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
        all_sources = [src[0] for src in sources_data]
        fetch_all_data(all_sources)
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
    # Ensure session state exists for the key
    if "refresh_interval_slider" not in st.session_state:
        st.session_state.refresh_interval_slider = 5
        
    auto_refresh_interval = st.sidebar.slider(
        "Interval (Minutes)", 
        min_value=1, 
        max_value=60, 
        key="refresh_interval_slider"
    )
    
    # Save to file on change
    try:
        interval_path = os.path.join(os.path.dirname(__file__), 'refresh_interval.txt')
        # Only write if the value actually differs from what we think is stored
        should_write = True
        if os.path.exists(interval_path):
            with open(interval_path, 'r') as f:
                if f.read().strip() == str(auto_refresh_interval):
                    should_write = False
        
        if should_write:
            with open(interval_path, 'w') as f:
                f.write(str(auto_refresh_interval))
    except:
        pass
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
selected_tz_name = st.sidebar.selectbox("Select Your Timezone", tz_names, index=default_tz_idx, key="user_timezone")
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
            <div style='color:#aaa;'>📡 Last Fetched: <b style='color:white'>{last_time_str}</b></div>
            <div style='color:#aaa;margin-top:4px;'>🔜 Next Refresh: <b style='color:white'>{next_time_str}</b></div>
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
                el.textContent = '⏳ Not Fetched Yet';
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
                el.textContent = '🔄 Updating...';
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
    /* Import Premium Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=Sarabun:wght@300;400;700&display=swap');
    
    body, .stApp, p, div, h1, h2, h3, span {
        font-family: 'Inter', 'Sarabun', sans-serif !important;
    }
    
    /* Navigation bar: neat multi-row with spacing */
    [data-testid="stRadio"] > div {
        flex-wrap: wrap !important;
        gap: 8px 12px !important;
    }
    [data-testid="stRadio"] > div > label {
        font-size: 14px !important;
        padding: 8px 16px !important;
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 50px !important;
        transition: all 0.2s ease !important;
    }
    [data-testid="stRadio"] > div > label:hover {
        background: rgba(255, 255, 255, 0.1) !important;
    }
    
    .news-card {
        background: rgba(255, 255, 255, 0.03);
        backdrop-filter: blur(8px);
        border-radius: 16px;
        padding: 18px;
        margin-bottom: 15px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }
    .news-card:hover {
        background: rgba(255, 255, 255, 0.07);
        transform: scale(1.02) translateY(-4px);
        border-color: rgba(66, 133, 244, 0.3);
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2), 0 10px 10px -5px rgba(0, 0, 0, 0.1);
    }
    .source-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 8px;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin-right: 12px;
        color: white;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }
    .category-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 8px;
        font-size: 11px;
        background: rgba(255, 255, 255, 0.12);
        color: #94A3B8;
        font-weight: 700;
        text-transform: uppercase;
    }
    .news-title {
        font-size: 17px;
        font-weight: 600;
        color: #F8FAFC;
        text-decoration: none;
        display: block;
        margin-top: 10px;
        line-height: 1.5;
        transition: color 0.2s ease;
    }
    .news-title:hover {
        color: #60A5FA !important;
    }
    .score-box {
        font-size: 22px;
        font-weight: 900;
        text-align: center;
        min-width: 50px;
        background: linear-gradient(135deg, #FF6B35, #FF4500);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    /* Hide default Streamlit button borders for a cleaner look */
    .stButton > button {
        border: none !important;
        background: transparent !important;
        font-size: 24px !important;
        padding: 0 !important;
        color: rgba(255, 255, 255, 0.4) !important;
        height: auto !important;
        line-height: 1 !important;
        transition: all 0.2s ease !important;
    }
    .stButton > button:hover {
        color: #FFF !important;
        transform: scale(1.2);
        background: transparent !important;
    }
</style>
</style>
""", unsafe_allow_html=True)

if not st.session_state.fetched_items:
    st.info("Feed is empty. Click 'Refresh Feed' in the sidebar to load the latest trends!")
else:
    # Calculate Total Score and Sort
    def get_total_score(item):
        item_id = item['id']
        global_vote_score = global_votes.get(item_id, 0)
        return item['base_score'] + global_vote_score

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
        "Space.com (Space News)": "Space.com",
        "MIT Tech Review (Tech News)": "MIT Tech Review",
        "Wired Magazine (Tech News)": "Wired",
        "Physics World (Science News)": "Physics World"
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
    file_path = os.path.join(os.path.dirname(__file__), 'current_feed.json')
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
                new_vote = 1 if current_vote <= 0 else 0
                update_global_vote(item_id, current_vote, new_vote)
                st.session_state.user_votes[item_id] = new_vote
                st.rerun()
                
            # Score
            st.markdown(f"<div class='score-box' style='color: {'#ff4500' if total_score > item['base_score'] else '#888'};'>{total_score}</div>", unsafe_allow_html=True)
            
            # Bury Button
            down_color = "#4285F4" if current_vote < 0 else "#666"
            if st.button("▼", key=f"down_{item_id}_{tab_prefix}"):
                new_vote = -1 if current_vote >= 0 else 0
                update_global_vote(item_id, current_vote, new_vote)
                st.session_state.user_votes[item_id] = new_vote
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
                "Space.com": "#00518A",
                "MIT Tech Review": "#A31F34",
                "Wired": "#000000",
                "Physics World": "#004B87"
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

    fixed_categories = ["Breaking", "Technology", "Education", "Politics", "Finance", "Economy", "Entertainment", "General"]
    tab_options = ["📊 Digg Stack", "All Feed", "Breaking", "Technology", "Education", "Politics", "Finance", "Economy", "Entertainment", "General"]
    if 'active_tab' not in st.session_state:
        st.session_state.active_tab = "📊 Digg Stack"
    with st.expander("☁️ Explore Topic Word Cloud (Independent Space Mode)"):
        if not st.session_state.get('fetched_items'):
            st.write("No data available for Word Cloud.")
        else:
            try:
                from collections import Counter
                import re

                # 1. Combined and Clean Text
                all_titles = " ".join([item['title'] for item in filtered_items])
                
                # 2. Expanded Stopwords (Thai + English)
                stop_words = set(thai_stopwords())
                extra_stops = {
                    'ที่', 'ซึ่ง', 'อัน', 'กับ', 'แก่', 'แต่', 'ต่อ', 'หรือ', 'และ', 'ของ', 'เป็น', 'ได้', 'ใน', 'จาก', 
                    'การ', 'ให้', 'ปี', 'วัน', 'เดือน', 'นี้', 'นั้น', 'ไป', 'มา', 'จะ', 'ทำ', 'ได้', 'ว่า', 'มี',
                    'อยู่', 'แล้ว', 'อีก', 'โดย', 'ตาม', 'เพื่อ', 'เมื่อ', 'ถึง', 'ก็', 'จะ', 'ได้', 'แบบ', 'เรื่อง',
                    'the', 'and', 'for', 'with', 'this', 'that', 'from', 'was', 'were', 'been', 'being', 'have', 'has',
                    'will', 'would', 'could', 'should', 'about', 'more', 'their', 'there', 'they', 'what', 'which', 'who',
                    'to', 'in', 'of', 'are', 'at', 'an', 'a', 'as', 'is', 'am', 'it', 'its', 'on', 'by', 'be', 'into', 'up', 
                    'out', 'over', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 
                    'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 
                    'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', 
                    'should', 'now', 'off', 'since', 'until', 'through', 'after', 'before', 'above', 'below', 'between',
                    'during', 'including', 'towards', 'upon', 'concerning', 'within', 'without'
                }
                stop_words.update(extra_stops)

                # 3. Tokenize and Count Frequency
                tokens = word_tokenize(all_titles)
                clean_tokens = []
                for t in tokens:
                    t_clean = t.strip().lower()
                    t_clean = re.sub(r"['\u2019]s$", "", t_clean)
                    if len(t_clean) > 1 and not t_clean.isdigit() and t_clean not in stop_words:
                        clean_tokens.append(t_clean)
                word_counts = Counter(clean_tokens).most_common(50) # Increased to 50 for more stars
                
                # Filter out very low frequency words if there are many words
                if len(word_counts) > 20:
                    word_counts = [wc for wc in word_counts if wc[1] > 1]
                
                word_counts = word_counts[:30] # Keep top 30 for UI
                
                if not word_counts:
                    st.write("Not enough significant words found.")
                elif WordCloud is None:
                    st.info("☁️ Word Cloud library is installing... Please wait a moment and refresh.")
                    # Show words as simple list as fallback
                    st.write(", ".join([f"{w}({c})" for w, c in word_counts]))
                else:
                    st.write("✨ Each star floats independently. Click to filter:")
                    
                    def select_word_callback(w):
                        st.session_state.search_input_val = w
                        if "search" in st.query_params:
                            st.query_params.clear()

                    # Custom CSS for Space-like Floating Animation on Native Buttons
                    st.markdown("""
                    <style>
                        div[data-testid="stExpander"] div[data-testid="stButton"] button {
                            background: rgba(255, 255, 255, 0.04) !important;
                            border: 1px solid rgba(255, 255, 255, 0.08) !important;
                            border-radius: 50px !important;
                            color: #CBD5E1 !important;
                            font-weight: 600 !important;
                            font-size: 13px !important;
                            padding: 8px 16px !important;
                            transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) !important;
                            animation: spaceFloat 10s ease-in-out infinite !important;
                            backdrop-filter: blur(4px);
                        }
                        
                        @keyframes spaceFloat {
                            0% { transform: translate(0, 0) rotate(0deg); }
                            33% { transform: translate(6px, -10px) rotate(1deg); }
                            66% { transform: translate(-4px, 10px) rotate(-1deg); }
                            100% { transform: translate(0, 0) rotate(0deg); }
                        }

                        div[data-testid="stExpander"] div[data-testid="stButton"] button:hover {
                            background: rgba(59, 130, 246, 0.2) !important;
                            border-color: #3B82F6 !important;
                            color: white !important;
                            transform: scale(1.15) !important;
                            box-shadow: 0 0 20px rgba(59, 130, 246, 0.5) !important;
                            z-index: 10;
                        }

                        div[data-testid="stExpander"] div[data-testid="stButton"]:nth-child(2n) button { animation-duration: 12s !important; animation-delay: -2s !important; }
                        div[data-testid="stExpander"] div[data-testid="stButton"]:nth-child(3n) button { animation-duration: 15s !important; animation-delay: -5s !important; }
                        div[data-testid="stExpander"] div[data-testid="stButton"]:nth-child(5n) button { animation-duration: 9s !important; animation-delay: -7s !important; }
                    </style>
                    """, unsafe_allow_html=True)
                    
                    # Display words as floating buttons
                    rows = [word_counts[i:i + 5] for i in range(0, len(word_counts), 5)]
                    for row_idx, row in enumerate(rows):
                        cols = st.columns(5)
                        for i, (word, count) in enumerate(row):
                            max_count = word_counts[0][1]
                            min_count = word_counts[-1][1]
                            is_top = count > (max_count + min_count) / 2
                            label = f"⭐ {word.upper()} ({count})" if is_top else f"{word} ({count})"
                            cols[i].button(label, key=f"wc_{row_idx}_{i}", on_click=select_word_callback, args=(word,), use_container_width=True)
            except Exception as e:
                st.error(f"Could not generate Word Cloud: {e}")

    tab_cols = st.columns(len(tab_options))
    for idx, opt in enumerate(tab_options):
        is_active = st.session_state.active_tab == opt
        if tab_cols[idx].button(opt, key=f"nav_btn_{idx}", use_container_width=True, type="primary" if is_active else "secondary"):
            st.session_state.active_tab = opt
            st.rerun()
    active_tab = st.session_state.active_tab
    
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
                
                const CATEGORIES = ["Breaking", "Technology", "Education", "Politics", "Finance", "Economy", "Entertainment", "General"];
                const COLORS = {
                    "Reddit": "#FF4500",
                    "Pantip": "#6366F1",
                    "Google News TH": "#3B82F6",
                    "Google News TH (IT)": "#F59E0B",
                    "BBC News": "#EF4444",
                    "CNN": "#DC2626",
                    "Al Jazeera": "#F97316",
                    "Thairath": "#10B981",
                    "Blognone": "#0EA5E9",
                    "The Standard": "#475569",
                    "Krungthep Turakij": "#1E40AF",
                    "Spaceth.co": "#334155",
                    "Phys.org": "#3B82F6",
                    "Space.com": "#0369A1",
                    "MIT Tech Review": "#E11D48",
                    "Wired": "#111827",
                    "Physics World": "#2563EB"
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
                        this.height = Math.max(25, Math.min(150, 25 + Math.floor(score / 10)));
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
                        
                        if (drawY + this.height < 0 || drawY > canvas.height) return; // Culling

                        // 1. Shadow & Glass Glow
                        ctx.save();
                        ctx.shadowColor = "rgba(0, 0, 0, 0.5)";
                        ctx.shadowBlur = 12;
                        ctx.shadowOffsetY = 6;
                        
                        // 2. Main Body (Semi-transparent for Glass effect)
                        ctx.fillStyle = this.color;
                        ctx.globalAlpha = 0.85;
                        ctx.beginPath();
                        if (ctx.roundRect) {
                            ctx.roundRect(this.x, drawY, this.width, this.height, 10);
                        } else {
                            ctx.rect(this.x, drawY, this.width, this.height);
                        }
                        ctx.fill();
                        ctx.globalAlpha = 1.0;
                        
                        // 3. Glossy Reflection
                        let grad = ctx.createLinearGradient(this.x, drawY, this.x + this.width, drawY + this.height);
                        grad.addColorStop(0, "rgba(255, 255, 255, 0.15)");
                        grad.addColorStop(0.5, "rgba(255, 255, 255, 0)");
                        grad.addColorStop(1, "rgba(0, 0, 0, 0.2)");
                        ctx.fillStyle = grad;
                        ctx.fill();
                        
                        // 4. Premium Border (Glass edge)
                        ctx.strokeStyle = "rgba(255, 255, 255, 0.25)";
                        ctx.lineWidth = 1.5;
                        ctx.stroke();
                        ctx.restore();
                        
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
                    let COL_WIDTH = canvas.width / COLUMNS;
                    
                    columnHeights = new Array(COLUMNS).fill(FLOOR_Y);
                    cameraY = new Array(COLUMNS).fill(0);
                    targetCameraY = new Array(COLUMNS).fill(0);
                    
                    // Load from sessionStorage
                    let storedBlocks = [];
                    try {
                        storedBlocks = JSON.parse(sessionStorage.getItem('diggBlocks') || '[]');
                    } catch(e) {}
                    
                    let restoredIds = new Set();
                    // Keep only blocks that are in the new rawData
                    let validStored = storedBlocks.filter(b => rawData.some(r => r.id === b.id));
                    
                    // Sort by y descending (bottom to top)
                    validStored.sort((a, b) => b.y - a.y);
                    
                    for (let stored of validStored) {
                        let data = rawData.find(r => r.id === stored.id);
                        let block = new Block(data, COL_WIDTH, FLOOR_Y);
                        block.y = stored.y;
                        block.stopped = false; // Allow falling if needed
                        blocks.push(block);
                        restoredIds.add(stored.id);
                    }
                    
                    // Filter queue to remove restored blocks
                    queue = rawData.filter(r => !restoredIds.has(r.id));
                    
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
                    // Scale mouse coordinates to match internal canvas resolution
                    mouseX = (e.clientX - rect.left) * (canvas.width / rect.width);
                    mouseY = (e.clientY - rect.top) * (canvas.height / rect.height);
                    
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
                    
                    // Save to sessionStorage
                    if (initialized) {
                        sessionStorage.setItem('diggBlocks', JSON.stringify(blocks.map(b => ({
                            id: b.data.id,
                            y: b.y
                        }))));
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
