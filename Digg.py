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
import re
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

# --- Global Thread Synchronization ---
STATE_LOCK = threading.Lock()
# Shared state accessible across threads without Disk I/O
GLOBAL_STATE = {
    "last_fetch_time": 0,
    "running": False,
    "latest_items": [],
    "user_tz": timezone(timedelta(hours=7)) # Default to Bangkok
}

# --- Pre-compiled Keywords for Categorization ---
CATEGORIES_KEYWORDS = {
    "Breaking": {
        "en": [re.compile(rf"\b{w}\b", re.I) for w in ['breaking', 'urgent', 'alert', 'crisis', 'latest', 'just in', 'live']],
        "th": ['ด่วน', 'ข่าวด่วน', 'อัปเดต', 'ประกาศสำคัญ', 'เกาะติด']
    },
    "Technology": {
        "en": [re.compile(rf"\b{w}\b", re.I) for w in ['tech', 'technology', 'smartphone', 'software', 'hardware', 'ai', 'cyber', 'robot', 'apple', 'google', 'microsoft', 'tesla', 'nvidia', 'semiconductor', 'quantum', 'startup', 'innovation']],
        "th": ['มือถือ', 'ไอที', 'คอมพิวเตอร์', 'หุ่นยนต์', 'สมาร์ทโฟน', 'แอพ', 'แอป', 'เทคโนโลยี', 'อวกาศ', 'นวัตกรรม', 'ยานยนต์ไฟฟ้า', 'อีวี', 'ปัญญาประดิษฐ์']
    },
    "Economy": {
        "en": [re.compile(rf"\b{w}\b", re.I) for w in ['economy', 'economic', 'gdp', 'inflation', 'trade', 'export', 'import', 'recession', 'tax', 'budget', 'tariff', 'fiscal', 'monetary']],
        "th": ['เศรษฐกิจ', 'ส่งออก', 'เงินเฟ้อ', 'จีดีพี', 'ภาษี', 'พาณิชย์', 'งบประมาณ', 'ดุลการค้า', 'ค่าเงิน']
    },
    "Finance": {
        "en": [re.compile(rf"\b{w}\b", re.I) for w in ['finance', 'bank', 'stock', 'crypto', 'investment', 'market', 'bitcoin', 'btc', 'eth', 'nasdaq', 'gold', 'dividend', 'portfolio', 'forex', 'insurance']],
        "th": ['หุ้น', 'การเงิน', 'ธนาคาร', 'คริปโต', 'บิทคอยน์', 'ทองคำ', 'ดอกเบี้ย', 'เงินฝาก', 'เซต', 'set', 'ปันผล', 'ลงทุน', 'กองทุน']
    },
    "Education": {
        "en": [re.compile(rf"\b{w}\b", re.I) for w in ['education', 'university', 'school', 'student', 'teacher', 'college', 'exam', 'scholarship', 'learning', 'academic', 'curriculum', 'literacy']],
        "th": ['การศึกษา', 'นักเรียน', 'นักศึกษา', 'มหาวิทยาลัย', 'โรงเรียน', 'สอบ', 'ทุนการศึกษา', 'เรียนต่อ', 'วิชาการ', 'ครู', 'หลักสูตร']
    },
    "Entertainment": {
        "en": [re.compile(rf"\b{w}\b", re.I) for w in ['entertainment', 'movie', 'music', 'celebrity', 'hollywood', 'netflix', 'kpop', 'anime', 'gaming', 'esports', 'drama', 'showbiz', 'streaming', 'concert']],
        "th": ['บันเทิง', 'ภาพยนตร์', 'หนัง', 'เพลง', 'ดารา', 'ซีรีส์', 'คอนเสิร์ต', 'เกม', 'ศิลปิน', 'ละคร', 'วงการบันเทิง', 'สตรีมมิ่ง']
    },
    "Politics": {
        "en": [re.compile(rf"\b{w}\b", re.I) for w in ['politics', 'government', 'election', 'president', 'minister', 'parliament', 'senate', 'diplomacy', 'starmer', 'biden', 'trump', 'putin', 'zelensky', 'cabinet', 'senator', 'congress', 'white house', 'labour', 'tory', 'republican', 'democrat', 'policy', 'sanction', 'treaty', 'summit', 'war', 'military', 'pentagon', 'defense', 'nato', 'un', 'asean', 'missile', 'nuclear', 'iran', 'israel', 'gaza', 'hamas', 'hezbollah', 'ukraine', 'russia', 'china', 'taiwan', 'irgc', 'cia', 'fbi', 'protest', 'veto', 'legal', 'court']],
        "th": ['การเมือง', 'เลือกตั้ง', 'รัฐบาล', 'นายก', 'สภา', 'ประท้วง', 'พรรค', 'ครม', 'รัฐมนตรี', 'ทักษิณ', 'ปชน', 'ปชป', 'ก้าวไกล', 'เพื่อไทย', 'ภูมิใจไทย', 'พลังประชารัฐ', 'ม็อบ', 'ชุมนุม', 'กฎหมาย', 'รัฐธรรมนูญ', 'ส.ส.', 'ส.ว.', 'วุฒิสภา', 'กกต', 'ปปช', 'ศาลรัฐธรรมนูญ', 'พ.ร.บ.', 'พ.ร.ก.', 'กม.', 'สงคราม', 'ทหาร', 'กลาโหม', 'ความมั่นคง', 'อาวุธ', 'อิหร่าน', 'อิสราเอล', 'ยูเครน', 'รัสเซีย', 'จีน', 'ไต้หวัน', 'พรรคร่วม', 'ปรับครม']
    },
    "General": {
        "en": [re.compile(rf"\b{w}\b", re.I) for w in ['news', 'general', 'world', 'local', 'society', 'culture', 'lifestyle', 'health', 'environment', 'weather', 'travel']],
        "th": ['ทั่วไป', 'สังคม', 'วัฒนธรรม', 'ชาวบ้าน', 'สรุป', 'รอบวัน', 'รอบโลก', 'สุขภาพ', 'สิ่งแวดล้อม', 'สภาพอากาศ', 'ท่องเที่ยว']
    }
}

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

import hashlib

def get_db_id(item_id):
    """Returns a Firebase-safe field name by hashing the item_id."""
    return hashlib.md5(item_id.encode()).hexdigest()

def update_global_vote(item_id, old_vote, new_vote):
    diff = (new_vote - old_vote) * 100
    if diff != 0 and db:
        try:
            db_id = get_db_id(item_id)
            doc_ref = db.collection('app_state').document('global_votes')
            doc_ref.set({db_id: firestore.Increment(diff)}, merge=True)
        except Exception as e:
            st.error(f"Error updating global vote: {e}")

@st.cache_data(ttl=60)
def get_cached_global_votes():
    """Fetches global votes from Firebase with a 60-second cache."""
    votes = {}
    if db:
        try:
            doc_ref = db.collection('app_state').document('global_votes')
            doc = doc_ref.get()
            if doc.exists:
                # Raw votes are stored by hashed ID
                votes = doc.to_dict()
        except:
            pass
    return votes

# --- Background Daemon System Globals ---
LATEST_NEWS = []
SEEN_IDS = set()

@st.cache_resource
def get_bg_config():
    return {
        "interval_minutes": 0,
        "sources": [],
        "last_fetch_time": 0,
        "running": False
    }

BG_CONFIG = get_bg_config()

# --- Page Config ---
st.set_page_config(page_title="My Local Digg", page_icon="📈", layout="wide", initial_sidebar_state="auto")

# --- Custom CSS for aesthetic (Global Consistently) ---
st.markdown("""
    <style>
    /* 1. Base Styles & Typography */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=Sarabun:wght@300;400;700&display=swap');
    
    html, body, [data-testid="stAppViewContainer"], .stApp, p, div, h1, h2, h3, span {
        font-family: 'Inter', 'Sarabun', sans-serif !important;
    }
    [data-testid="stAppViewContainer"] {
        background-color: #0F172A !important; /* Deeper Dark Blue */
    }

    /* =========================================
       2. THE PERFECT SIDEBAR TOGGLE FIX 
       ========================================= */

    /* 2.1 ซ่อน SVG เดิมของ Streamlit ถาวร */
    [data-testid="stSidebarCollapseButton"] svg,
    button[data-testid="stExpandSidebarButton"] svg {
        display: none !important;
    }

    /* เคลียร์กรอบนอกของปุ่ม Collapse (เมื่อกาง Sidebar) เพื่อไม่ให้เกิดวงกลมซ้อน */
    [data-testid="stSidebarCollapseButton"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        min-width: 40px !important;
        min-height: 40px !important;
    }

    /* 2.2 ตกแต่งปุ่ม Collapse จริงวงใน (บางเบา สไตล์พรีเมียม 1px) */
    [data-testid="stSidebarCollapseButton"] button {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        background-color: #1E293B !important; /* สีน้ำเงินสเลทเข้ม */
        border: 1px solid rgba(255, 255, 255, 0.4) !important; /* เส้นขอบขาวบางพรีเมียม */
        border-radius: 50% !important;
        width: 40px !important;
        height: 40px !important;
        min-width: 40px !important;
        min-height: 40px !important;
        position: relative !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        cursor: pointer !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3) !important;
        padding: 0 !important;
        margin: 0 !important;
    }

    /* เคลียร์กรอบนอกของปุ่ม Expand (เมื่อหุบ Sidebar) เพื่อไม่ให้เกิดวงกลมซ้อน */
    div[data-testid="stSidebarCollapsedControl"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        width: auto !important;
        height: auto !important;
    }

    /* 2.3 ตกแต่งปุ่ม Expand จริง (สีส้มแดงนีออนเจิดจ้า 1px ขนาด 40px) */
    button[data-testid="stExpandSidebarButton"] {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        background-color: #FF4500 !important; /* สีส้มแดง */
        border: 1px solid rgba(255, 255, 255, 0.6) !important; /* เส้นขอบบางเฉียบ */
        border-radius: 50% !important;
        width: 40px !important;
        height: 40px !important;
        min-width: 40px !important;
        min-height: 40px !important;
        position: fixed !important;
        top: 15px !important;
        left: 15px !important;
        z-index: 999999 !important;
        box-shadow: 0 0 15px rgba(255, 69, 0, 0.4) !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        cursor: pointer !important;
        opacity: 1 !important;
        visibility: visible !important;
        transform: none !important;
        padding: 0 !important;
        margin: 0 !important;
    }

    /* 2.4 ลูกศร "ซ่อน" (ชี้ซ้าย - จัดตำแหน่งกึ่งกลางเชิงทัศนศาสตร์อย่างสมบูรณ์แบบ) */
    [data-testid="stSidebarCollapseButton"] button::after {
        content: "«" !important;
        position: absolute !important;
        color: #FFFFFF !important;
        font-size: 22px !important; /* ขนาดพอดีคำ ไม่หนาเทอะทะ */
        font-weight: 700 !important; /* ความหนากำลังดี */
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        top: 41% !important; /* ปรับลดลงมา 5px เพื่อความสมดุลเชิงทัศนศาสตร์อย่างสมบูรณ์แบบ */
        left: 50% !important;
        transform: translate(-50%, -50%) !important;
        pointer-events: none !important;
        line-height: 1 !important;
    }

    /* 2.5 ลูกศร "แสดง" (ชี้ขวา - จัดตำแหน่งกึ่งกลางเชิงทัศนศาสตร์อย่างสมบูรณ์แบบ) */
    button[data-testid="stExpandSidebarButton"]::after {
        content: "»" !important;
        position: absolute !important;
        color: #FFFFFF !important;
        font-size: 22px !important;
        font-weight: 700 !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        top: 41% !important; /* ปรับลดลงมา 5px เช่นกัน */
        left: 50% !important;
        transform: translate(-50%, -50%) !important;
        pointer-events: none !important;
        line-height: 1 !important;
    }

    /* 2.6 Hover Effects (ขยายตัวแบบสมูท 10% พร้อมไฟนีออนฟ้าหรูหรา) */
    [data-testid="stSidebarCollapseButton"] button:hover {
        background-color: #3B82F6 !important; /* สีน้ำเงินฟ้านีออน */
        border-color: #FFFFFF !important;
        transform: scale(1.1) !important;
        box-shadow: 0 0 15px rgba(59, 130, 246, 0.6) !important;
    }

    button[data-testid="stExpandSidebarButton"]:hover {
        background-color: #3B82F6 !important;
        border-color: #FFFFFF !important;
        transform: scale(1.1) !important;
        box-shadow: 0 0 15px rgba(59, 130, 246, 0.6) !important;
    }

    /* 3. Top-Right Menu Fix (Targeting ONLY the App Menu) */
    /* Use very specific aria-label to avoid sidebar conflict */
    button[aria-label*="menu"],
    button[aria-label*="Menu"],
    button[aria-label*="App menu"] {
        position: relative !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        min-width: 40px !important;
    }
    
    button[aria-label*="menu"] span,
    button[aria-label*="App menu"] span { display: none !important; }
    
    button[aria-label*="menu"]::after,
    button[aria-label*="App menu"]::after {
        content: "⋮" !important; /* 3 Dots Icon */
        font-size: 24px !important;
        color: #F8FAFC !important;
        position: absolute !important;
        display: block !important;
        visibility: visible !important;
        top: 50% !important;
        left: 50% !important;
        transform: translate(-50%, -50%) !important;
    }

    [data-testid="stExpanderIcon"], [data-testid="stIconMaterial"] { display: none !important; }
    [data-testid="stExpander"] summary {
        display: flex !important;
        align-items: center !important;
        justify-content: space-between !important;
    }
    [data-testid="stExpander"] summary::after {
        content: "▼";
        font-size: 12px;
        color: #F8FAFC;
        margin-left: auto;
        transition: transform 0.3s ease;
    }
    [data-testid="stExpander"][open] summary::after { transform: rotate(180deg); }
    [data-testid="stExpander"] summary p {
        padding-left: 10px;
        font-size: 16px !important;
        font-weight: 700 !important;
        color: #F8FAFC !important;
        margin: 0 !important;
    }
    [data-testid="stExpander"] {
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 12px !important;
        background: rgba(255, 255, 255, 0.05) !important;
        margin-bottom: 1rem !important;
    }

    /* 4. Radio Navigation Bar */
    [data-testid="stRadio"] > div { flex-wrap: wrap !important; gap: 8px 12px !important; }
    [data-testid="stRadio"] > div > label {
        font-size: 14px !important;
        padding: 8px 16px !important;
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 50px !important;
        transition: all 0.2s ease !important;
    }
    [data-testid="stRadio"] > div > label:hover { background: rgba(255, 255, 255, 0.1) !important; }

    /* 5. News Card Aesthetic */
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
    }
    .news-card:hover {
        background: rgba(255, 255, 255, 0.07);
        transform: scale(1.02) translateY(-4px);
        border-color: rgba(66, 133, 244, 0.3);
    }
    .score-box {
        font-size: 22px;
        font-weight: 900;
        text-align: center;
        background: linear-gradient(135deg, #FF6B35, #FF4500);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    .stButton > button {
        border: none !important;
        background: transparent !important;
        font-size: 24px !important;
        padding: 0 !important;
        color: rgba(255, 255, 255, 0.4) !important;
        transition: all 0.2s ease !important;
    }
    .stButton > button:hover {
        color: #FFF !important;
        transform: scale(1.2);
    }

    /* =========================================
       6. MOBILE OPTIMIZATIONS (@media queries)
       ========================================= */
    @media (max-width: 768px) {
        /* ลดระยะห่างขอบจอให้เนื้อหาเต็มขึ้น */
        .main .block-container {
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            padding-top: 2rem !important;
        }

        /* ปรับหน้าตา Card ข่าวให้เหมาะกับจอแนวตั้ง */
        .news-card {
            padding: 14px !important;
            margin-bottom: 12px !important;
            flex-direction: column !important;
            align-items: flex-start !important;
            gap: 12px !important;
        }

        .news-content {
            width: 100% !important;
        }

        /* ปรับปุ่มโหวตให้อยู่ในแถวเดียวกันด้านล่าง */
        .vote-controls {
            display: flex !important;
            flex-direction: row !important;
            align-items: center !important;
            justify-content: flex-start !important;
            gap: 20px !important;
            width: 100% !important;
            border-top: 1px solid rgba(255,255,255,0.05) !important;
            padding-top: 10px !important;
        }

        .score-box {
            font-size: 18px !important;
        }

        /* ปรับขนาดหัวข้อข่าว */
        .news-title {
            font-size: 16px !important;
            line-height: 1.4 !important;
        }

        /* ปรับปุ่ม Toggle Sidebar ให้เล็กลงนิดนึงบนมือถือ */
        [data-testid="stSidebarCollapseButton"] button,
        [data-testid="stSidebarCollapseButton"] {
            min-width: 40px !important;
            min-height: 40px !important;
        }
        button[data-testid="stExpandSidebarButton"] {
            width: 40px !important;
            height: 40px !important;
            top: 10px !important;
            left: 10px !important;
        }
    }

    /* =========================================
       7. ADAPTIVE NAVIGATION (Laptops/Small Screens)
       ========================================= */
    @media (max-width: 1400px) {
        /* Force 11-column navigation block (menu) into a 4-column grid */
        [data-testid="stHorizontalBlock"]:has(> div:nth-child(11)) {
            display: grid !important;
            grid-template-columns: repeat(4, 1fr) !important;
            gap: 10px !important;
        }
        [data-testid="stHorizontalBlock"]:has(> div:nth-child(11)) > div {
            width: 100% !important;
            max-width: 100% !important;
            flex: 1 1 auto !important;
        }

        /* Word cloud horizontal block layout */
        [data-testid="stExpander"] [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
            gap: 10px !important;
            justify-content: flex-start !important;
        }
        [data-testid="stExpander"] [data-testid="stHorizontalBlock"] > div {
            flex: 1 1 18% !important; /* 5 columns roughly */
            min-width: 100px !important;
            max-width: 20% !important;
        }

        [data-testid="stHorizontalBlock"]:has(> div:nth-child(11)) button,
        [data-testid="stExpander"] button {
            padding: 8px 4px !important;
            font-size: 13px !important;
            height: 45px !important; /* Fixed height for grid alignment */
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
        }

        /* Adjust main news grid to 2 columns on medium screens if it was 3 */
        [data-testid="stMain"] [data-testid="stHorizontalBlock"]:not([data-testid="stHorizontalBlock"]:has(> div:nth-child(11))) > div {
            min-width: 40% !important;
            flex: 1 1 auto !important;
        }
    }

    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"]:has(> div:nth-child(11)) {
            grid-template-columns: repeat(3, 1fr) !important; /* 3 columns on mobile */
        }
        [data-testid="stHorizontalBlock"]:has(> div:nth-child(11)) > div {
            width: 100% !important;
            max-width: 100% !important;
        }
        [data-testid="stMain"] [data-testid="stHorizontalBlock"] > div {
            min-width: 100% !important;
        }
    }

    /* 8. Masonry & Sticky Layout */
    .masonry-container {
        column-count: 3;
        column-gap: 15px;
        width: 100%;
    }
    .masonry-item {
        break-inside: avoid;
        margin-bottom: 15px;
        display: block;
    }
    
    @media (max-width: 1200px) { .masonry-container { column-count: 2; } }
    @media (max-width: 600px) { .masonry-container { column-count: 1; } }

    .sticky-nav {
        position: sticky;
        top: 0;
        z-index: 999;
        background: rgba(15, 23, 42, 0.9);
        backdrop-filter: blur(10px);
        padding: 10px 0;
        margin-bottom: 20px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    }
    </style>
""", unsafe_allow_html=True)

# --- State Management ---
if "user_votes" not in st.session_state:
    st.session_state.user_votes = {} # dict mapping item_id -> vote modifier (+1 or -1)
if "fetched_items" not in st.session_state:
    st.session_state.fetched_items = []

# --- Global Votes (Cached) ---
global_votes = get_cached_global_votes()

# --- Data Fetching Functions ---
import re

def assign_topic_category(text_to_search, fallback_category):
    text_lower = text_to_search.lower()
    
    for category, langs in CATEGORIES_KEYWORDS.items():
        # 1. Check English keywords (Pre-compiled Regex)
        for pattern in langs["en"]:
            if pattern.search(text_lower):
                return category
        
        # 2. Check Thai keywords (Substring match)
        for th_word in langs["th"]:
            if th_word in text_lower:
                return category
            
    return fallback_category


@st.cache_data(ttl=600)
def get_word_cloud_data(all_titles):
    """Heavy ThaiNLP tokenization cached for 10 minutes."""
    # 1. Aggressive Stop Words (Thai + English)
    stop_words = set(thai_stopwords())
    extra_stops = {
        'ที่', 'ซึ่ง', 'อัน', 'กับ', 'แก่', 'แต่', 'ต่อ', 'หรือ', 'และ', 'ของ', 'เป็น', 'ได้', 'ใน', 'จาก', 
        'การ', 'ให้', 'ปี', 'วัน', 'เดือน', 'นี้', 'นั้น', 'ไป', 'มา', 'จะ', 'ทำ', 'ได้', 'ว่า', 'มี',
        'อยู่', 'แล้ว', 'อีก', 'โดย', 'ตาม', 'เพื่อ', 'เมื่อ', 'ถึง', 'ก็', 'จะ', 'ได้', 'แบบ', 'เรื่อง',
        'เผย', 'แจง', 'ชี้', 'แนะ', 'รุด', 'ลุย', 'ปัด', 'โต้', 'ผุด', 'ส่อ', 'เปิด', 'จัด', 'รับ', 'พบ', 'พบว่า',
        'เขา', 'เธอ', 'เรา', 'มัน', 'คุณ', 'ท่าน', 'พวก', 'เรา', 'หนู', 'ผม', 'ดิฉัน', 'แก', 'ใคร', 'อะไร', 'ไหน',
        'the', 'and', 'for', 'with', 'this', 'that', 'from', 'was', 'were', 'been', 'being', 'have', 'has',
        'will', 'would', 'could', 'should', 'about', 'more', 'their', 'there', 'they', 'what', 'which', 'who',
        'to', 'in', 'of', 'are', 'at', 'an', 'a', 'as', 'is', 'am', 'it', 'its', 'on', 'by', 'be', 'into', 'up', 
        'out', 'over', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 
        'how', 'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 
        'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', 
        'should', 'now', 'off', 'since', 'until', 'through', 'after', 'before', 'above', 'below', 'between',
        'during', 'including', 'towards', 'upon', 'concerning', 'within', 'without',
        'he', 'his', 'him', 'she', 'her', 'hers', 'it', 'its', 'they', 'them', 'their', 'theirs', 'we', 'us', 'our', 'ours', 'you', 'your', 'yours',
        'like', 'says', 'said', 'told', 'going', 'does', 'did', 'been', 'has', 'have', 'had', 'may', 'might', 'must',
        'http', 'https', 'www', 'com', 'org', 'net', 'co', 'th', 'html', 'url', 'link', 'amp', 'gt', 'lt',
        'rt', 're', 'via', 'facebook', 'twitter', 'instagram', 'tiktok', 'youtube', 'news', 'breaking',
        'make', 'made', 'my', 'me', 'mine', 'if', 'early', 'back', 'did', 'didn', 'do', 'does', 'dont', 'join', 'joined',
        'one', 'two', 'new', 'now', 'get', 'got', 'see', 'saw', 'top', 'best', 'more', 'most', 'some', 'many', 'any',
        'take', 'took', 'using', 'used', 'way', 'well', 'want', 'wants', 'know', 'known', 'think', 'thought',
        'but', 'big', 'need', 'needs', 'man', 'men', 'much', 'many', 'great', 'good', 'bad', 'just', 'very', 'even',
        'time', 'life', 'day', 'days', 'year', 'years', 'world', 'people', 'home', 'work', 'call', 'called', 'still'
    }
    stop_words.update(extra_stops)

    # 2. Aggressive Cleaning & Tokenization
    tokens = word_tokenize(all_titles)
    clean_tokens = []
    for t in tokens:
        t_clean = t.strip().lower()
        # Remove possessives and symbols
        t_clean = re.sub(r"['\u2019]s$", "", t_clean)
        t_clean = re.sub(r"[^\w\u0E00-\u0E7F]", "", t_clean) # Keep only Alphanum + Thai, remove spaces/punct
        
        if len(t_clean) > 1 and not t_clean.isdigit() and t_clean not in stop_words:
            clean_tokens.append(t_clean)
    
    return Counter(clean_tokens).most_common(50)

def check_keyword_match(keyword, text_lower):
    """
    Highly optimized keyword matcher.
    """
    if not keyword: return False
    
    # Check if keyword contains Thai characters
    has_thai = any('\u0E00' <= c <= '\u0E7F' for c in keyword)
    
    if has_thai:
        return keyword in text_lower
    else:
        # English: Word boundary check
        return re.search(rf'\b{re.escape(keyword)}\b', text_lower, re.I) is not None

def enrich_item(item):
    """Adds category, watchlist metadata, and fetch time to an item once."""
    title_lower = item['title'].lower()
    item['category'] = assign_topic_category(title_lower, item.get('category', 'General'))
    
    # Store raw epoch timestamp for dynamic UI timezone conversion
    item['fetch_timestamp'] = time.time()
    
    # Store formatted fetch time using the thread-safe global timezone (fallback)
    try:
        with STATE_LOCK:
            active_tz = GLOBAL_STATE.get("user_tz", timezone(timedelta(hours=7)))
        item['fetch_time'] = datetime.now(timezone.utc).astimezone(active_tz).strftime("%H:%M:%S")
    except:
        item['fetch_time'] = datetime.now().strftime("%H:%M:%S")
    
    # Watchlist check
    item['is_monitored'] = False
    item['match_color'] = "#FFD700"
    
    # Use global monitored words if available, else session state
    # This is a bit tricky with threads, so we'll pass them in or use a lock
    monitored = monitored_words if 'monitored_words' in globals() else []
    for word in monitored:
        if check_keyword_match(word, title_lower):
            item['is_monitored'] = True
            item['match_color'] = kw_colors.get(word, "#FFD700")
            break
    return item

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
            item = {
                "id": f"reddit_{post['id']}",
                "title": post['title'],
                "url": f"https://www.reddit.com{post['permalink']}",
                "source": "Reddit",
                "base_score": post['score'],
                "category": "General" # Initial
            }
            items.append(enrich_item(item))
        return items
    except Exception as e:
        return []

def fetch_rss(feed_url, source_name, category):
    try:
        source_boosts = {
            "Reuters": 1000, "AP News": 1000, "BBC News": 800, "The Information": 600,
            "Axios": 600, "CNN": 400, "Al Jazeera": 400, "MIT Tech Review": 500, "Wired": 400,
            "Bloomberg": 1000, "Wall Street Journal": 1000, "JS100": 800, "Isranews": 500, "Matichon": 500,
            "Google News Int": 500
        }
        base_score = source_boosts.get(source_name, 100)
        
        feed = feedparser.parse(feed_url)
        items = []
        for entry in feed.entries[:10]:
            item = {
                "id": f"rss_{source_name}_{entry.id if hasattr(entry, 'id') else entry.link}",
                "title": entry.title,
                "url": entry.link,
                "source": source_name,
                "base_score": base_score,
                "category": category
            }
            items.append(enrich_item(item))
        return items
    except Exception as e:
        return []

def fetch_pantip():
    url = "https://pantip.com/"
    headers = {"User-agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.content, 'html.parser')
        items = []
        links = soup.find_all('a', href=True)
        added_urls = set()
        for link in links:
            href = link['href']
            title = link.text.strip()
            if '/topic/' in href and len(title) > 20 and href not in added_urls:
                item = {
                    "id": f"pantip_{href.split('/')[-1]}",
                    "title": title,
                    "url": href if href.startswith('http') else f"https://pantip.com{href}",
                    "source": "Pantip",
                    "base_score": 250,
                    "category": "General"
                }
                items.append(enrich_item(item))
                added_urls.add(href)
            if len(items) >= 10:
                break
        return items
    except Exception as e:
        return []

def fetch_nitter(path, source_name, category):
    instances = [
        "https://nitter.perennialte.ch", "https://nitter.projectsegfau.lt", "https://nitter.moomoo.me",
        "https://xcancel.com", "https://nitter.cz", "https://nitter.no-logs.com"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def check_instance(instance):
        url = f"{instance}{path}"
        try:
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                feed = feedparser.parse(response.text)
                if feed.entries: return feed.entries
        except: pass
        return None

    with ThreadPoolExecutor(max_workers=len(instances)) as executor:
        futures = {executor.submit(check_instance, inst): inst for inst in instances}
        for future in as_completed(futures):
            try:
                entries = future.result()
                if entries:
                    source_boosts = {"The Information": 600, "Axios": 600}
                    base_score = source_boosts.get(source_name, 100)
                    items = []
                    for entry in entries[:10]:
                        item = {
                            "id": f"nitter_{source_name}_{entry.link}",
                            "title": entry.title,
                            "url": entry.link,
                            "source": source_name,
                            "base_score": base_score,
                            "category": category
                        }
                        items.append(enrich_item(item))
                    return items
            except: pass
    return []

def get_raw_data(sources_selected):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    all_items = []
    
    fetch_configs = [
        ("Reddit (Global Trends)", fetch_reddit, ()),
        ("BBC (Global News)", fetch_rss, ("http://feeds.bbci.co.uk/news/rss.xml", "BBC News", "General")),
        ("Bloomberg (Business News)", fetch_rss, ("https://news.google.com/rss/search?q=site:bloomberg.com&hl=en-US&gl=US&ceid=US:en", "Bloomberg", "Economy")),
        ("Google News (International)", fetch_rss, ("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en", "Google News Int", "General")),
        ("Google News (Thailand)", fetch_rss, ("https://news.google.com/rss?hl=th&gl=TH&ceid=TH:th", "Google News TH", "General")),
        ("Google News TH (IT)", fetch_rss, ("https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pKVGlnQVAB?hl=th&gl=TH&ceid=TH:th", "Google News TH (IT)", "Technology")),
        ("Isranews (Thai News)", fetch_rss, ("https://news.google.com/rss/search?q=site:isranews.org&hl=th&gl=TH&ceid=TH:th", "Isranews", "General")),
        ("JS100 (Traffic & News)", fetch_rss, ("https://news.google.com/rss/search?q=site:js100.com&hl=th&gl=TH&ceid=TH:th", "JS100", "Breaking")),
        ("Matichon (Thai News)", fetch_rss, ("https://www.matichon.co.th/feed", "Matichon", "General")),
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
        ("Physics World (Science News)", fetch_rss, ("https://physicsworld.com/feed/", "Physics World", "Technology")),
        ("Wall Street Journal (Business News)", fetch_rss, ("https://news.google.com/rss/search?q=site:wsj.com&hl=en-US&gl=US&ceid=US:en", "Wall Street Journal", "Economy")),
        ("X (Twitter Trends)", fetch_nitter, ("/search/rss?q=news", "X (Twitter)", "Breaking")),
        ("TikTok Trends", fetch_rss, ("https://news.google.com/rss/search?q=site:tiktok.com+news&hl=en-US&gl=US&ceid=US:en", "TikTok", "Entertainment")),
        ("Threads Trends", fetch_rss, ("https://news.google.com/rss/search?q=site:threads.net+news&hl=en-US&gl=US&ceid=US:en", "Threads", "General")),
        ("Instagram Trends", fetch_rss, ("https://news.google.com/rss/search?q=site:instagram.com+news&hl=en-US&gl=US&ceid=US:en", "Instagram", "Entertainment")),
        ("Reuters (World News)", fetch_rss, ("https://news.google.com/rss/search?q=site:reuters.com&hl=en-US&gl=US&ceid=US:en", "Reuters", "General")),
        ("Associated Press (AP)", fetch_rss, ("https://news.google.com/rss/search?q=site:apnews.com&hl=en-US&gl=US&ceid=US:en", "AP News", "General")),
        ("The Information (Tech)", fetch_nitter, ("/theinformation/rss", "The Information", "Technology")),
        ("Axios (News)", fetch_nitter, ("/axios/rss", "Axios", "Technology"))
    ]
    
    # Optimized max_workers to 15 to reduce resource contention
    with ThreadPoolExecutor(max_workers=15) as executor:
        future_to_source = {
            executor.submit(func, *args): name 
            for name, func, args in fetch_configs 
            if name in sources_selected
        }
        
        for future in as_completed(future_to_source):
            try:
                all_items.extend(future.result(timeout=5))
            except: continue
                
    return all_items


def fetch_all_data(sources_selected):
    with st.spinner("🔄 Fetching news from all sources..."):
        st.toast("🗞️ Starting news fetch...", icon="🔄")
        all_items = get_raw_data(sources_selected)
        if not all_items:
            st.error("Failed to fetch news.")
        st.session_state.fetched_items = all_items
    
    fetch_time = time.time()
    st.session_state['last_fetch_time'] = fetch_time
    
    with STATE_LOCK:
        GLOBAL_STATE["last_fetch_time"] = fetch_time
        GLOBAL_STATE["latest_items"] = all_items
    
    global SEEN_IDS
    for item in all_items:
        SEEN_IDS.add(item['id'])

def bg_fetch_loop():
    global SEEN_IDS, LATEST_NEWS
    while True:
        with STATE_LOCK:
            interval = BG_CONFIG["interval_minutes"]
            running = BG_CONFIG.get("running", False)
            last_fetch = BG_CONFIG["last_fetch_time"]
            selected_sources = BG_CONFIG.get("sources", [])
        
        if interval > 0 and running:
            now = time.time()
            if now - last_fetch > interval * 60:
                try:
                    new_items = get_raw_data(selected_sources)
                    with STATE_LOCK:
                        for item in new_items:
                            if item['id'] not in SEEN_IDS:
                                SEEN_IDS.add(item['id'])
                                LATEST_NEWS.append(item)
                                GLOBAL_STATE["latest_items"].append(item)
                        
                        GLOBAL_STATE["last_fetch_time"] = time.time()
                        BG_CONFIG["last_fetch_time"] = GLOBAL_STATE["last_fetch_time"]
                except: pass
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
if 'search_input_val' not in st.session_state:
    st.session_state.search_input_val = ""

def clear_search_query():
    st.session_state.search_input_val = ""

def select_word_callback(w):
    st.session_state.search_input_val = w

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
            margin-left: 15px !important; 
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


sources_data = sorted([
    ("Reuters (World News)", "🟠 **Reuters**"),
    ("Associated Press (AP)", "🔴 **AP News**"),
    ("Axios (News)", "🟦 **Axios**"),
    ("TikTok Trends", "🎵 **TikTok Trends**"),
    ("Threads Trends", "🧵 **Threads Trends**"),
    ("Instagram Trends", "📸 **Instagram Trends**"),
    ("Al Jazeera (Global News)", "🟡 **Al Jazeera**"),
    ("BBC (Global News)", "🟥 **BBC News**"),
    ("Bloomberg (Business News)", "📈 **Bloomberg**"),
    ("Blognone (IT News)", "🌐 **Blognone**"),
    ("CNN (Global News)", "🔴 **CNN**"),
    ("Google News (International)", "🟦 **Google News Int**"),
    ("Google News (Thailand)", "🟦 **Google News TH**"),
    ("Google News TH (IT)", "🟨 **Google News TH (IT)**"),
    ("Isranews (Thai News)", "📰 **Isranews**"),
    ("JS100 (Traffic & News)", "📻 **JS100**"),
    ("Krungthep Turakij (Business News)", "🔵 **Krungthep Turakij**"),
    ("Matichon (Thai News)", "🗞️ **Matichon**"),
    ("MIT Tech Review (Tech News)", "🦾 **MIT Tech Review**"),
    ("Pantip (Thai Trends)", "🟪 **Pantip**"),
    ("Physics World (Science News)", "⚛️ **Physics World**"),
    ("Physics.org (Science News)", "🔬 **Phys.org**"),
    ("Reddit (Global Trends)", "🟧 **Reddit**"),
    ("Space.com (Space News)", "🌌 **Space.com**"),
    ("Spaceth.co (Space News)", "🚀 **Spaceth.co**"),
    ("The Information (Tech)", "⬛ **The Information**"),
    ("The Standard (Thai News)", "⚫ **The Standard**"),
    ("Thairath (Thai News)", "🟢 **Thairath**"),
    ("Wall Street Journal (Business News)", "📰 **Wall Street Journal**"),
    ("Wired Magazine (Tech News)", "🔌 **Wired**"),
    ("X (Twitter Trends)", "🐦 **X (Twitter)**")
], key=lambda x: x[0])

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
                content = f.read().strip()
                if content:
                    return content.split(",")
    except: pass
    return [src[0] for src in sources_data] # Default to ALL

def load_monitored_keywords():
    try:
        path = os.path.join(os.path.dirname(__file__), 'monitored_keywords.txt')
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read().strip()
    except: pass
    return ""

def save_monitored_keywords(keywords):
    try:
        path = os.path.join(os.path.dirname(__file__), 'monitored_keywords.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(keywords)
    except: pass

# Initialize states from file if session is fresh
if 'cb_initialized' not in st.session_state:
    saved = load_selections()
    for internal_name, _ in sources_data:
        st.session_state[f"cb_{internal_name}"] = internal_name in saved
    st.session_state.monitored_keywords = load_monitored_keywords()
    st.session_state.cb_initialized = True

MATCH_PALETTE = ["#FFD700", "#00FFFF", "#39FF14", "#FF00FF", "#FFA500", "#FF3131", "#1F51FF", "#F0E68C"]

def on_keywords_change():
    new_val = st.session_state.monitored_keywords
    save_monitored_keywords(new_val)
    
    words = [w.strip().lower() for w in new_val.replace("\n", ",").split(",") if w.strip()]
    colors = {word: MATCH_PALETTE[i % len(MATCH_PALETTE)] for i, word in enumerate(words)}
    
    if 'fetched_items' in st.session_state and st.session_state.fetched_items:
        for item in st.session_state.fetched_items:
            title_lower = item['title'].lower()
            item['is_monitored'] = False
            item['match_color'] = "#FFD700"
            for word in words:
                if check_keyword_match(word, title_lower):
                    item['is_monitored'] = True
                    item['match_color'] = colors.get(word, "#FFD700")
                    break

st.sidebar.markdown("### 🎯 Watchlist")
monitored_input = st.sidebar.text_area("Monitored Keywords (comma separated)", 
                                     key="monitored_keywords",
                                     placeholder="e.g. AI, Tesla, ก้าวไกล",
                                     help="Items matching these words will be highlighted and added to the 'Watchlist' tab.",
                                     on_change=on_keywords_change)

# Improved splitting: handle commas and newlines (allow spaces within phrases)
monitored_words = [w.strip().lower() for w in monitored_input.replace("\n", ",").split(",") if w.strip()]

# Assign unique colors to each keyword
kw_colors = {word: MATCH_PALETTE[i % len(MATCH_PALETTE)] for i, word in enumerate(monitored_words)}

# User feedback in sidebar
if monitored_words:
    # Count matches across ALL fetched items
    all_items = st.session_state.get('fetched_items', [])
    match_count = sum(1 for item in all_items if any(check_keyword_match(w, item['title'].lower()) for w in monitored_words))
    st.sidebar.caption(f"🎯 Monitoring {len(monitored_words)} words | Found {match_count} matches")

st.sidebar.markdown("---")
st.sidebar.markdown("### 📰 News Sources")

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

thai_sources = {
    "Google News (Thailand)", "Google News TH (IT)", "Isranews (Thai News)",
    "JS100 (Traffic & News)", "Krungthep Turakij (Business News)", "Matichon (Thai News)",
    "Pantip (Thai Trends)", "Spaceth.co (Space News)", "The Standard (Thai News)",
    "Thairath (Thai News)", "Blognone (IT News)"
}

with st.sidebar.expander("🇹🇭 ประเทศไทย (Thailand)", expanded=True):
    col_sel_th, col_clr_th = st.columns(2)
    if col_sel_th.button("Select All TH", key="sel_th", use_container_width=True):
        for internal_name, _ in sources_data:
            if internal_name in thai_sources:
                st.session_state[f"cb_{internal_name}"] = True
        st.rerun()
    if col_clr_th.button("Clear All TH", key="clr_th", use_container_width=True):
        for internal_name, _ in sources_data:
            if internal_name in thai_sources:
                st.session_state[f"cb_{internal_name}"] = False
        st.rerun()
        
    for internal_name, display_name in sources_data:
        if internal_name in thai_sources:
            key = f"cb_{internal_name}"
            val = st.checkbox(display_name, key=key)
            if val:
                selected_sources.append(internal_name)

with st.sidebar.expander("🌐 ต่างประเทศ (International)", expanded=True):
    col_sel_int, col_clr_int = st.columns(2)
    if col_sel_int.button("Select All INT", key="sel_int", use_container_width=True):
        for internal_name, _ in sources_data:
            if internal_name not in thai_sources:
                st.session_state[f"cb_{internal_name}"] = True
        st.rerun()
    if col_clr_int.button("Clear All INT", key="clr_int", use_container_width=True):
        for internal_name, _ in sources_data:
            if internal_name not in thai_sources:
                st.session_state[f"cb_{internal_name}"] = False
        st.rerun()
        
    for internal_name, display_name in sources_data:
        if internal_name not in thai_sources:
            key = f"cb_{internal_name}"
            val = st.checkbox(display_name, key=key)
            if val:
                selected_sources.append(internal_name)

# --- FAIL-SAFE REMOVED to allow explicit empty state ---
# if not selected_sources:
#     selected_sources = [src[0] for src in sources_data]

st.sidebar.caption(f"📂 Sources selected: {len(selected_sources)} / {len(sources_data)}")
if search_query:
    st.sidebar.caption(f"🔍 Active Search: '{search_query}'")

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

def on_start_stop_click():
    st.session_state.running_state = not st.session_state.running_state
    try:
        file_path = os.path.join(os.path.dirname(__file__), 'running_state.txt')
        with open(file_path, 'w') as f:
            f.write(str(st.session_state.running_state))
    except: pass
    
    if st.session_state.running_state:
        BG_CONFIG["running"] = True
    else:
        BG_CONFIG["running"] = False
        BG_CONFIG["interval_minutes"] = 0
        st.session_state.fetched_items = []

# START/STOP button
if st.session_state.running_state:
    st.sidebar.button("⏹ STOP", use_container_width=True, type="primary", key="stop_btn", on_click=on_start_stop_click)
else:
    st.sidebar.button("▶ START", use_container_width=True, type="primary", key="start_btn", on_click=on_start_stop_click)

# Trigger fetch if running but empty
if st.session_state.get('running_state', False) and not st.session_state.get('fetched_items'):
    all_sources_list = [src[0] for src in sources_data]
    fetch_all_data(all_sources_list)

btn_bg = "#00CC44" if st.session_state.running_state else "#CC0000"
st.sidebar.markdown(f"""
<style>
    [data-testid="stSidebar"] button[kind="primary"] {{
        background-color: {btn_bg} !important;
        color: white !important;
    }}
</style>
""", unsafe_allow_html=True)

st.sidebar.subheader("🔄 Auto Refresh")
enable_auto = st.sidebar.toggle("Enable Background Fetching", value=True)

if enable_auto:
    if "refresh_interval_slider" not in st.session_state:
        st.session_state.refresh_interval_slider = 5
    auto_refresh_interval = st.sidebar.slider("Interval (Minutes)", min_value=1, max_value=60, key="refresh_interval_slider")
else:
    auto_refresh_interval = 0

# --- Timezone ---
st.sidebar.subheader("🌐 Timezone")
TIMEZONE_OPTIONS = {"UTC+07:00 (Bangkok/Jakarta)": 7, "UTC+00:00 (London/GMT)": 0, "UTC-08:00 (Pacific US)": -8, "UTC-05:00 (Eastern US)": -5}
selected_tz_name = st.sidebar.selectbox("Select Your Timezone", list(TIMEZONE_OPTIONS.keys()), index=0)
user_tz = timezone(timedelta(hours=TIMEZONE_OPTIONS[selected_tz_name]))

with STATE_LOCK:
    GLOBAL_STATE["user_tz"] = user_tz

def format_ts(ts):
    if ts <= 0: return "--:--:--"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(user_tz)
    return dt.strftime("%H:%M:%S")

if st.session_state.get('running_state', False):
    BG_CONFIG["interval_minutes"] = auto_refresh_interval
    BG_CONFIG["running"] = True
else:
    BG_CONFIG["interval_minutes"] = 0
    BG_CONFIG["running"] = False
BG_CONFIG["sources"] = selected_sources

if enable_auto and auto_refresh_interval > 0 and st.session_state.get('running_state', False):
    last_fetch = st.session_state.get('last_fetch_time', 0)
    with STATE_LOCK:
        global_ts = GLOBAL_STATE.get("last_fetch_time", 0)
        global_items = GLOBAL_STATE.get("latest_items", [])
    
    if global_ts > last_fetch:
        st.session_state['last_fetch_time'] = global_ts
        # Sync latest items from background thread to UI session
        st.session_state['fetched_items'] = global_items
        st.rerun()

    last_time_str = format_ts(last_fetch)
    next_time_str = format_ts(last_fetch + auto_refresh_interval * 60) if last_fetch > 0 else "--:--:--"
    with st.sidebar:
        components.html(f"""
        <div style='background:rgba(255,255,255,0.08);border-radius:8px;padding:10px;font-size:12px;font-family:sans-serif;'>
            <div style='color:#aaa;'>📡 Last Fetched: <b style='color:white'>{last_time_str}</b></div>
            <div style='color:#aaa;margin-top:4px;'>🔜 Next Refresh: <b style='color:white'>{next_time_str}</b></div>
            <div id='cd' style='font-weight:bold;font-size:16px;margin-top:4px;color:#00CC44;'>--:--</div>
        </div>
        <script>
        const fetchTs = {int(last_fetch * 1000)};
        const intervalMs = {auto_refresh_interval * 60 * 1000};
        function tick() {{
            const el = document.getElementById('cd');
            if (!el || fetchTs === 0) return;
            const remaining = Math.max(0, intervalMs - (Date.now() - fetchTs));
            const mins = String(Math.floor(remaining / 60000)).padStart(2,'0');
            const secs = String(Math.floor((remaining % 60000) / 1000)).padStart(2,'0');
            el.textContent = (remaining <= 30000 ? '⚡ ' : '✅ ') + mins + ':' + secs;
            if (remaining === 0) setTimeout(() => window.top.location.reload(), 2000);
        }}
        setInterval(tick, 1000); tick();
        </script>""", height=105)


st.sidebar.markdown("---")
st.sidebar.markdown("<div style='text-align: center; color: #bbb; font-size: 15px;'>Credits: <b style='color: white;'>Joopiest Udomsaph</b></div>", unsafe_allow_html=True)

# --- Main Feed Logic ---
if not st.session_state.get('fetched_items'):
    if st.session_state.get('running_state', False):
        with st.status("📡 System is running but feed is empty. Attempting to recover data...", expanded=True) as status:
            all_sources_list = [src[0] for src in sources_data]
            fetch_all_data(all_sources_list)
            status.update(label="✅ Data recovered!", state="complete", expanded=False)
        st.rerun()
    else:
        st.info("🚀 Feed is empty. Click '▶ START' in the sidebar to load trending news!")
else:
    def get_total_score(item):
        db_id = get_db_id(item['id'])
        local_vote_boost = st.session_state.user_votes.get(item['id'], 0) * 100
        return item['base_score'] + global_votes.get(db_id, 0) + local_vote_boost

    SOURCE_MAPPING = {
        "Reuters (World News)": "Reuters", "Associated Press (AP)": "AP News", "The Information (Tech)": "The Information",
        "Axios (News)": "Axios", "TikTok Trends": "TikTok",
        "Threads Trends": "Threads", "Instagram Trends": "Instagram", "Reddit (Global Trends)": "Reddit",
        "Pantip (Thai Trends)": "Pantip", "Google News (Thailand)": "Google News TH", "Google News TH (IT)": "Google News TH (IT)",
        "Google News (International)": "Google News Int",
        "BBC (Global News)": "BBC News", "CNN (Global News)": "CNN", "Al Jazeera (Global News)": "Al Jazeera",
        "Thairath (Thai News)": "Thairath", "Blognone (IT News)": "Blognone", "The Standard (Thai News)": "The Standard",
        "Krungthep Turakij (Business News)": "Krungthep Turakij", "Spaceth.co (Space News)": "Spaceth.co",
        "Physics.org (Science News)": "Phys.org", "Space.com (Space News)": "Space.com", "MIT Tech Review (Tech News)": "MIT Tech Review",
        "Wired Magazine (Tech News)": "Wired", "Physics World (Science News)": "Physics World", "X (Twitter Trends)": "X (Twitter)",
        "Isranews (Thai News)": "Isranews", "Matichon (Thai News)": "Matichon", "Bloomberg (Business News)": "Bloomberg",
        "Wall Street Journal (Business News)": "Wall Street Journal", "JS100 (Traffic & News)": "JS100"
    }
    
    allowed_names = [SOURCE_MAPPING.get(src, src) for src in selected_sources]
    
    # Revert to stable source-based filtering
    filtered_items = [item for item in st.session_state.fetched_items if item['source'] in allowed_names]
            
    if search_query:
        filtered_items = [item for item in filtered_items if search_query.lower() in item['title'].lower()]
    
    sorted_items = sorted(filtered_items, key=get_total_score, reverse=True)

    def render_item(item, tab_prefix):
        total_score = get_total_score(item)
        item_id = item['id']
        current_vote = st.session_state.user_votes.get(item_id, 0)
        
        # Metadata pre-calculated during fetch
        is_monitored = item.get('is_monitored', False)
        match_color = item.get('match_color', "#FFD700")
        category = item.get('category', 'General')
        
        col_vote, col_content = st.columns([2.5, 7.5])
        with col_vote:
            if st.button("▲", key=f"up_{item_id}_{tab_prefix}"):
                new_vote = 1 if current_vote <= 0 else 0
                update_global_vote(item_id, current_vote, new_vote)
                st.session_state.user_votes[item_id] = new_vote
                st.rerun()
            st.markdown(f"<div class='score-box' style='color: {'#ff4500' if total_score > item['base_score'] else '#888'};'>{total_score}</div>", unsafe_allow_html=True)
            if st.button("▼", key=f"down_{item_id}_{tab_prefix}"):
                new_vote = -1 if current_vote >= 0 else 0
                update_global_vote(item_id, current_vote, new_vote)
                st.session_state.user_votes[item_id] = new_vote
                st.rerun()

        with col_content:
            source_colors = {
                "Reuters": "#FF8000", "AP News": "#D2232A", "The Information": "#000000", "Axios": "#005994",
                "TikTok": "#EE1D52", "Threads": "#000000", "Instagram": "#C13584", "Reddit": "#FF4500", "Pantip": "#3f3652",
                "Google News TH": "#4285F4", "Google News TH (IT)": "#FBBC05", "Google News Int": "#1A73E8", "BBC News": "#B80000", "CNN": "#CC0000",
                "Al Jazeera": "#FF9900", "Thairath": "#009944", "Blognone": "#0EA5E9", "The Standard": "#475569",
                "Krungthep Turakij": "#1E40AF", "Spaceth.co": "#334155", "Phys.org": "#3B82F6", "Space.com": "#0369A1",
                "MIT Tech Review": "#A31F34", "Wired": "#111827", "Physics World": "#2563EB", "X (Twitter)": "#000000",
                "Isranews": "#0F766E", "Matichon": "#4338CA", "Bloomberg": "#0564F2", "Wall Street Journal": "#1F2937", "JS100": "#EA580C"
            }
            bg_color = source_colors.get(item['source'], "#444")
            card_class = "news-card monitored-card" if is_monitored else "news-card"
            card_style = f"border: 3px solid {match_color}; box-shadow: 0 0 15px {match_color}44;" if is_monitored else ""
            match_badge = f'<span style="background-color: {match_color}; color: #000; padding: 2px 8px; border-radius: 4px; font-weight: 900; font-size: 11px; margin-right: 8px; box-shadow: 0 0 15px {match_color}; animation: match-pulse 1s infinite;">🎯 WATCHLIST</span>' if is_monitored else ""
            
            st.markdown(f'<div class="{card_class}" style="{card_style}"><div style="flex: 1;"><span class="source-badge" style="background-color: {bg_color};">{item["source"]}</span> <span class="category-badge">{category}</span> {match_badge}<br><a class="news-title" href="{item["url"]}" target="_blank" style="color: {match_color if is_monitored else "white"} !important; font-weight: {"900" if is_monitored else "normal"};">{item["title"]}</a></div></div>', unsafe_allow_html=True)

    tab_options = ["📊 Digg Stack", "All Feed", "🎯 Watchlist", "Breaking", "Technology", "Education", "Politics", "Finance", "Economy", "Entertainment", "General"]
    active_tab = st.session_state.get('active_tab', "📊 Digg Stack")
    
    with st.expander("☁️ Explore Topic Word Cloud"):
        all_titles = " ".join([item['title'] for item in filtered_items])
        word_counts = get_word_cloud_data(all_titles)
        
        st.write("✨ Trending Keyword Star Field:")
        rows = [word_counts[i:i+5] for i in range(0, len(word_counts), 5)]
        for r_idx, row in enumerate(rows):
            cols = st.columns(5)
            for i, (w, c) in enumerate(row):
                cols[i].button(f"{w} ({c})", key=f"wc_{r_idx}_{i}", on_click=select_word_callback, args=(w,), use_container_width=True)

    # Wrap navigation in a sticky div
    st.markdown('<div class="sticky-nav">', unsafe_allow_html=True)
    tab_cols = st.columns(len(tab_options))
    for idx, opt in enumerate(tab_options):
        if tab_cols[idx].button(opt, key=f"nav_{idx}", type="primary" if active_tab == opt else "secondary", use_container_width=True):
            st.session_state.active_tab = opt; st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    if active_tab == "All Feed":
        cols = st.columns(3)
        for idx, item in enumerate(sorted_items):
            with cols[idx % 3]: render_item(item, f"all_{idx}")
    elif active_tab == "🎯 Watchlist":
        # Use ALL fetched items for Watchlist, ignoring source/search filters
        all_fetched = st.session_state.get('fetched_items', [])
        watch_items = [item for item in all_fetched if item.get('is_monitored', False)]
        watch_items = sorted(watch_items, key=get_total_score, reverse=True)
        
        if not watch_items: st.info("No items match your watchlist keywords.")
        else:
            cols = st.columns(3)
            for idx, item in enumerate(watch_items):
                with cols[idx % 3]: render_item(item, f"watch_{idx}")
    elif active_tab == "📊 Digg Stack":
        # Minimized serialization for Digg Stack
        stack_data = []
        for item in sorted_items:
            # Dynamically format raw epoch timestamp based on LATEST selected timezone
            raw_ts = item.get('fetch_timestamp')
            if raw_ts:
                formatted_time = format_ts(raw_ts)
            else:
                formatted_time = item.get('fetch_time', '--:--:--')
                
            stack_data.append({
                "id": item['id'], 
                "title": item['title'], 
                "category": item.get('category', 'General'), 
                "score": get_total_score(item), 
                "url": item['url'], 
                "source": item['source'],
                "is_monitored": item.get('is_monitored', False),
                "match_color": item.get('match_color', "#FFD700"),
                "fetch_time": formatted_time
            })
        js_data = json.dumps(stack_data)

        html_code = """
        <!-- FORCE RELOAD V3 -->
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { margin: 0; background-color: #1E1E1E; color: white; font-family: sans-serif; overflow: hidden; }
                canvas { display: block; width: 100%; height: 750px; }
            </style>
        </head>
        <body>
            <canvas id="diggCanvas"></canvas>
            <script>
                const canvas = document.getElementById('diggCanvas');
                const ctx = canvas.getContext('2d');
                
                // Ensure canvas matches iframe size
                canvas.width = window.innerWidth;
                canvas.height = 750; 
                let rawData = []; // Populated by Python
                let isSystemRunning = false; // Populated by Python
                
                const CATEGORIES = ["Breaking", "Technology", "Education", "Politics", "Finance", "Economy", "Entertainment", "General"];
                const COLORS = {
                    "Reuters": "#FF8000",
                    "AP News": "#D2232A",
                    "The Information": "#000000",
                    "Axios": "#005994",
                    "TikTok": "#EE1D52",
                    "Threads": "#FFFFFF",
                    "Instagram": "#C13584",
                    "Reddit": "#FF4500",
                    "Pantip": "#6366F1",
                    "Google News TH": "#3B82F6",
                    "Google News TH (IT)": "#F59E0B",
                    "Google News Int": "#1A73E8",
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
                    "Physics World": "#2563EB",
                    "X (Twitter)": "#000000",
                    "Isranews": "#0F766E",
                    "Matichon": "#4338CA",
                    "Bloomberg": "#0564F2",
                    "Wall Street Journal": "#1F2937",
                    "JS100": "#EA580C"
                };
                
                let blocks = [];
                let queue = [];
                let columnHeights = [];
                let particles = []; // Particle system array
                let initialized = false;
                
                class Particle {
                    constructor(x, y, color) {
                        this.x = x;
                        this.y = y;
                        this.color = color;
                        this.vx = (Math.random() - 0.5) * 12; // More explosive width
                        this.vy = (Math.random() - 1.2) * 14; // Higher initial pop
                        this.life = 1.0;
                        this.decay = 0.015 + Math.random() * 0.02; // Slower fade
                        this.size = 3 + Math.random() * 5; // Larger particles
                    }
                    update() {
                        this.x += this.vx;
                        this.y += this.vy;
                        this.vy += 0.35; // Stronger gravity
                        this.life -= this.decay;
                    }
                    draw() {
                        if (this.life <= 0) return;
                        ctx.save();
                        ctx.fillStyle = this.color;
                        ctx.globalAlpha = this.life;
                        // Add glow to particles
                        ctx.shadowBlur = 10;
                        ctx.shadowColor = this.color;
                        ctx.beginPath();
                        ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
                        ctx.fill();
                        ctx.restore();
                    }
                }

                function spawnSparks(x, y, color, count = 25) { // More sparks
                    for (let i = 0; i < count; i++) {
                        particles.push(new Particle(x, y, color));
                    }
                }
                
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
                        this.height = Math.max(35, Math.min(200, 35 + Math.floor(score / 5)));
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
                                // IMPACT! Spawn sparks
                                spawnSparks(this.x + this.width / 2, this.y + this.height, this.color, 15);
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
                        
                        // --- HIGHLIGHT MONITORED BLOCKS (BLINKING/PULSING WITH UNIQUE COLOR) ---
                        if (this.data.is_monitored) {
                            let mColor = this.data.match_color || "#FFD700";
                            let pulse = 15 + Math.sin(Date.now() / 200) * 10; // Dynamic blur
                            ctx.shadowColor = mColor;
                            ctx.shadowBlur = pulse;
                            ctx.strokeStyle = mColor; // Keep border color stable but glow pulses
                            ctx.lineWidth = 5;
                            ctx.globalAlpha = 1.0;
                        }

                        ctx.beginPath();
                        if (ctx.roundRect) {
                            ctx.roundRect(this.x, drawY, this.width, this.height, 10);
                        } else {
                            ctx.rect(this.x, drawY, this.width, this.height);
                        }
                        ctx.fill();
                        
                        if (this.data.is_monitored) {
                            ctx.stroke(); // Draw the thick golden border
                        }
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
                        ctx.fillStyle = "#FFFFFF";
                        ctx.font = "800 14px 'Inter', 'Sarabun', sans-serif";
                        ctx.textBaseline = "middle";
                        ctx.textAlign = "center";
                        
                        let maxChars = Math.max(2, Math.floor(this.width / 9.5));
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
                            ctx.font = "800 14px 'Inter', 'Sarabun', sans-serif";
                            ctx.fillText(title, this.x + this.width/2, drawY + this.height/2 - 10);
                            ctx.font = "bold 11px 'Inter', sans-serif";
                            ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
                            let timeStr = this.data.fetch_time || "--:--";
                            ctx.fillText("🔥 " + scoreVal.toLocaleString() + "  |  🕒 " + timeStr, this.x + this.width/2, drawY + this.height/2 + 10);
                        } else {
                            ctx.font = "800 13px 'Inter', 'Sarabun', sans-serif";
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
                        let maxScroll = Math.max(0, 100 - columnHeights[col]);
                        // Disable auto-panning completely to prevent columns from visually "going up" on their own
                        // The user can still scroll manually with the mouse wheel or click the label to snap.
                    }
                }
                
                async function init() {
                    if (canvas.height === 0) {
                        setTimeout(init, 100);
                        return;
                    }
                    if (!rawData || rawData.length === 0) {
                        blocks = []; queue = []; initialized = true;
                        return;
                    }
                    queue = [...rawData];
                    let COLUMNS = CATEGORIES.length;
                    let FLOOR_Y = canvas.height - 40;
                    let COL_WIDTH = canvas.width / COLUMNS;
                    
                    columnHeights = new Array(COLUMNS).fill(FLOOR_Y);
                    cameraY = new Array(COLUMNS).fill(0);
                    targetCameraY = new Array(COLUMNS).fill(0);
                    
                    let storedBlocks = [];
                    try {
                        storedBlocks = JSON.parse(sessionStorage.getItem('diggBlocks') || '[]');
                    } catch(e) {}
                    
                    let restoredIds = new Set();
                    let validStored = storedBlocks.filter(b => rawData.some(r => r.id === b.id));
                    validStored.sort((a, b) => b.y - a.y);
                    
                    for (let stored of validStored) {
                        let data = rawData.find(r => r.id === stored.id);
                        let block = new Block(data, COL_WIDTH, FLOOR_Y);
                        block.y = stored.y;
                        block.stopped = false; 
                        blocks.push(block);
                        restoredIds.add(stored.id);
                    }
                    
                    queue = rawData.filter(r => !restoredIds.has(r.id));
                    initialized = true;
                }
                init();
                setInterval(spawnBlock, 600);
                
                canvas.addEventListener('wheel', (e) => {
                    if (initialized && hoveredCol !== -1) {
                        e.preventDefault(); 
                        targetCameraY[hoveredCol] += e.deltaY * 0.5; 
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
                    mouseX = (e.clientX - rect.left) * (canvas.width / rect.width);
                    mouseY = (e.clientY - rect.top) * (canvas.height / rect.height);
                    hoveredBlockUrl = null;
                    hoveredBlockSource = null;
                    hoveredBlockTitle = null;
                    hoveredBlockFetchTime = null;
                    hoveredCol = -1;
                    canvas.style.cursor = 'default';
                    
                    if (initialized) {
                        let COL_WIDTH = canvas.width / CATEGORIES.length;
                        hoveredCol = Math.floor(mouseX / COL_WIDTH);
                        if (hoveredCol >= CATEGORIES.length) hoveredCol = CATEGORIES.length - 1;
                        if (hoveredCol < 0) hoveredCol = 0;
                    }
                    
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
                        let maxScroll = Math.max(0, 100 - columnHeights[hoveredCol]);
                        if (targetCameraY[hoveredCol] > maxScroll / 2) {
                            targetCameraY[hoveredCol] = 0;
                        } else {
                            targetCameraY[hoveredCol] = maxScroll; 
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
                        ctx.fillStyle = "rgba(255, 255, 255, 0.4)";
                        ctx.font = "18px 'Inter', sans-serif";
                        ctx.textAlign = "center";
                        if (isSystemRunning) {
                            ctx.fillText("🔍 No news matches your filters or search query.", canvas.width/2, canvas.height/2 - 10);
                            ctx.font = "14px 'Inter', sans-serif";
                            ctx.fillText("Check selected sources and keywords in sidebar.", canvas.width/2, canvas.height/2 + 20);
                        } else {
                            ctx.fillText("🚀 System is stopped. Click 'START' to explore news.", canvas.width/2, canvas.height/2);
                        }
                    }
                    
                    if (initialized) {
                        for (let i = 0; i < COLUMNS; i++) {
                            let maxScroll = Math.max(0, 100 - columnHeights[i]);
                            // Auto-sink so newest blocks are visible at the top
                            // Pause this auto-sinking if the user is hovering over this column
                            if (hoveredCol !== i) {
                                targetCameraY[i] = maxScroll;
                            }
                            cameraY[i] += (targetCameraY[i] - cameraY[i]) * 0.1;
                        }
                    }
                    
                    for (let block of blocks) {
                        block.update();
                        block.draw();
                    }

                    // --- NEW: Update and Draw Particles (Sparks) ---
                    for (let i = particles.length - 1; i >= 0; i--) {
                        particles[i].update();
                        particles[i].draw();
                        if (particles[i].life <= 0) particles.splice(i, 1);
                    }
                    
                    if (initialized) {
                        sessionStorage.setItem('diggBlocks', JSON.stringify(blocks.map(b => ({
                            id: b.data.id,
                            y: b.y
                        }))));
                    }
                    
                    // Draw Sticky Footer
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
                    
                    // Draw Hover Tooltip
                    if (hoveredBlockSource) {
                        const TOOLTIP_PADDING = 15;
                        const LINE_HEIGHT = 22;
                        const HEADER_FONT = "bold 15px 'Inter', sans-serif";
                        const BODY_FONT = "14px 'Inter', 'Sarabun', sans-serif";
                        
                        ctx.font = HEADER_FONT;
                        let line1 = "📰 " + hoveredBlockSource;
                        let line2 = "🕒 Fetched: " + (hoveredBlockFetchTime || '--:--:--');
                        
                        ctx.font = BODY_FONT;
                        let fullTitle = hoveredBlockTitle || '';
                        let maxTooltipW = 380; 
                        let titleLines = [];
                        
                        let words = fullTitle.split(' ');
                        let currentLine = '';
                        for (let word of words) {
                            let testLine = currentLine + (currentLine ? ' ' : '') + word;
                            if (ctx.measureText(testLine).width > maxTooltipW - (TOOLTIP_PADDING * 2)) {
                                if (currentLine) {
                                    titleLines.push(currentLine);
                                    currentLine = word;
                                } else {
                                    let chars = word.split('');
                                    for (let ch of chars) {
                                        if (ctx.measureText(currentLine + ch).width > maxTooltipW - (TOOLTIP_PADDING * 2)) {
                                            titleLines.push(currentLine);
                                            currentLine = ch;
                                        } else {
                                            currentLine += ch;
                                        }
                                    }
                                }
                            } else {
                                currentLine = testLine;
                            }
                        }
                        if (currentLine) titleLines.push(currentLine);
                        
                        if (titleLines.length > 5) {
                            titleLines = titleLines.slice(0, 5);
                            titleLines[4] += '...';
                        }
                        
                        ctx.font = HEADER_FONT;
                        let w1 = ctx.measureText(line1).width;
                        let w2 = ctx.measureText(line2).width;
                        ctx.font = BODY_FONT;
                        let maxTitleW = 0;
                        for (let tl of titleLines) {
                            let tw = ctx.measureText(tl).width;
                            if (tw > maxTitleW) maxTitleW = tw;
                        }
                        
                        let tooltipW = Math.min(maxTooltipW, Math.max(w1, w2, maxTitleW) + (TOOLTIP_PADDING * 2));
                        let tooltipH = TOOLTIP_PADDING + (LINE_HEIGHT * 2) + 8 + (LINE_HEIGHT * titleLines.length) + 12;
                        
                        let tx = mouseX + 15;
                        let ty = mouseY + 15;
                        if (tx + tooltipW > canvas.width) tx = mouseX - tooltipW - 10;
                        if (ty + tooltipH > canvas.height) ty = mouseY - tooltipH - 10;
                        
                        ctx.fillStyle = "rgba(15, 23, 42, 0.96)";
                        ctx.beginPath();
                        if (ctx.roundRect) ctx.roundRect(tx, ty, tooltipW, tooltipH, 12);
                        else ctx.rect(tx, ty, tooltipW, tooltipH);
                        ctx.fill();
                        
                        ctx.strokeStyle = "rgba(255, 255, 255, 0.2)";
                        ctx.lineWidth = 1.5;
                        ctx.stroke();
                        
                        ctx.textAlign = "left";
                        ctx.textBaseline = "top";
                        
                        ctx.fillStyle = "#FACC15"; 
                        ctx.font = HEADER_FONT;
                        ctx.fillText(line1, tx + TOOLTIP_PADDING, ty + TOOLTIP_PADDING);
                        
                        ctx.fillStyle = "#4ADE80"; 
                        ctx.fillText(line2, tx + TOOLTIP_PADDING, ty + TOOLTIP_PADDING + LINE_HEIGHT);
                        
                        ctx.strokeStyle = "rgba(255, 255, 255, 0.1)";
                        ctx.beginPath();
                        let sepY = ty + TOOLTIP_PADDING + (LINE_HEIGHT * 2) + 4;
                        ctx.moveTo(tx + TOOLTIP_PADDING, sepY);
                        ctx.lineTo(tx + tooltipW - TOOLTIP_PADDING, sepY);
                        ctx.stroke();
                        
                        ctx.fillStyle = "#FFFFFF";
                        ctx.font = BODY_FONT;
                        for (let li = 0; li < titleLines.length; li++) {
                            ctx.fillText(titleLines[li], tx + TOOLTIP_PADDING, sepY + 8 + (li * LINE_HEIGHT));
                        }
                    }
                    
                    requestAnimationFrame(animate);
                }
                
                animate();
            </script>
        </body>
        </html>
        """
        # Inject data and state
        processed_html = html_code.replace('let rawData = [];', f'let rawData = {js_data};')
        processed_html = processed_html.replace('let isSystemRunning = false;', f'let isSystemRunning = {"true" if st.session_state.get("running_state", False) else "false"};')
        components.html(processed_html, height=750)
    else:
        cat_items = [item for item in sorted_items if item['category'] == active_tab]
        if not cat_items:
            st.info(f"No news found in the {active_tab} category matching your filters.")
        else:
            cols = st.columns(3)
            for idx, item in enumerate(cat_items):
                with cols[idx % 3]: render_item(item, f"cat_{idx}")

