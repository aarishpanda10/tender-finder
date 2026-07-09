import base64
import io
import re
import urllib.parse
from datetime import date, datetime
import gc

import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from PIL import Image, ImageEnhance
import pytesseract
from pytesseract import Output

# ----------------------------------------------------------------------
# 1. PREMIUM 3D SLIDING UI / UX INJECTION
# ----------------------------------------------------------------------
st.set_page_config(page_title="Executive Security | Tender Desk", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
    /* 3D Scrolling Parallax Background */
    @keyframes slideBG {
        0% { background-position: 0% 50%; }
        100% { background-position: 100% 50%; }
    }
    .stApp {
        /* ========================================================================
           TO USE YOUR OWN IMAGE FROM executivesecurity.in:
           1. Go to your website, right-click any image, and click "Copy image address"
           2. Paste that link between the single quotes below, replacing the unsplash link.
           ========================================================================
        */
        background: linear-gradient(rgba(10, 25, 47, 0.88), rgba(15, 45, 82, 0.88)), 
                    url('https://images.unsplash.com/photo-1497366216548-37526070297c?q=80&w=2000&auto=format&fit=crop');
        background-size: cover;
        animation: slideBG 45s linear infinite alternate;
        color: #ffffff;
        background-attachment: fixed;
    }
    
    /* Glassmorphism Dashboard Container */
    .block-container {
        padding-top: 3rem !important;
        max-width: 1200px;
        background: rgba(255, 255, 255, 0.03);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-radius: 24px;
        border: 1px solid rgba(255, 255, 255, 0.15);
        box-shadow: 0 15px 35px 0 rgba(0, 0, 0, 0.4);
        margin-top: 2rem;
        margin-bottom: 2rem;
    }

    /* Executive Branding Typography */
    .company-title { 
        font-family: 'Arial Black', sans-serif; color: #ffffff; font-size: 3.8rem; 
        text-align: center; margin-bottom: 0px; padding-bottom: 0px; letter-spacing: 3px;
        text-transform: uppercase; text-shadow: 3px 3px 6px rgba(0,0,0,0.6);
    }
    .company-subtitle { 
        color: #e63946; font-weight: 900; text-align: center; font-size: 1.3rem; 
        margin-top: 5px; margin-bottom: 3rem; letter-spacing: 5px; text-shadow: 1px 1px 3px rgba(0,0,0,0.5);
    }

    /* Form Fields & Inputs */
    div[data-baseweb="select"] > div, input {
        background-color: rgba(255, 255, 255, 0.95) !important; border-radius: 10px !important; border: 2px solid transparent !important;
    }
    div[data-baseweb="select"] > div:focus, input:focus { border: 2px solid #e63946 !important; }
    label { color: #f1f5f9 !important; font-weight: 700 !important; font-size: 1.15rem !important; letter-spacing: 1px;}
    
    /* Premium Action Button */
    div.stButton > button:first-child { 
        background: linear-gradient(135deg, #e63946 0%, #a80a13 100%); color: #ffffff; 
        font-weight: 900; font-size: 1.4rem; border-radius: 12px; border: 1px solid rgba(255,255,255,0.2); 
        padding: 0.8rem 2rem; transition: all 0.3s ease; box-shadow: 0 6px 20px rgba(230, 57, 70, 0.5);
    }
    div.stButton > button:first-child:hover { 
        transform: translateY(-3px) scale(1.02); box-shadow: 0 10px 25px rgba(230, 57, 70, 0.7); color: white;
    }

    /* Result Cards */
    div[data-testid="stExpander"] { 
        background: rgba(10, 30, 60, 0.7) !important; border-radius: 14px; 
        border: 1px solid rgba(255, 255, 255, 0.2); color: white !important; backdrop-filter: blur(10px);
    }
    div[data-testid="stExpander"] p, div[data-testid="stExpander"] span { color: #e2e8f0; }
    .stProgress > div > div > div > div { background-color: #e63946; }
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='company-title'>🛡️ EXECUTIVE SECURITY</div>", unsafe_allow_html=True)
st.markdown("<div class='company-subtitle'>AUTOMATED TENDER INTELLIGENCE DESK</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------
# 2. KEYWORD CONFIGURATION
# ----------------------------------------------------------------------
TENDER_WORDS = [
    "TENDER", "CORRIGENDUM", "NIT", "NOTICE INVITING TENDER",
    "E-TENDER", "E TENDER", "EXPRESSION OF INTEREST", "EOI",
    "RFP", "REQUEST FOR PROPOSAL", "RFQ", "REQUEST FOR QUOTATION",
    "INVITATION FOR BIDS", "INVITATION OF BIDS", "IFB",
    "ADDENDUM", "TENDER CALL NOTICE", "AWARD OF CONTRACT",
    "SELECTION OF AGENCY", "EMPANELMENT", "BID DOCUMENT",
]
SERVICE_WORDS = [
    "SECURITY", "HOUSEKEEPING", "HOUSE KEEPING", "MANPOWER",
    "WATCHMAN", "WATCHMEN", "GUARD", "GUARDS", "OUTSOURC", 
    "FACILITY MANAGEMENT", "SECURITY GUARD", "SECURITY PERSONNEL",
    "CFMS", "UPKEEPING", "CLEANING", "MAINTENANCE", "SANITATION",
    "SWEEPER", "PEON", "PARAMEDIC", "NURSING", "TECHNO-MANAGERIAL",
    "SUPPORT STAFF", "MULTI TASKING STAFF", "MTS", "DATA ENTRY OPERATOR",
    "DEO", "ATTENDANT", "DRIVER", "WARD BOY", "SERVICE PROVIDER",
]

# ----------------------------------------------------------------------
# 3. HIGH-SPEED SCRAPING (Skips first 2 pages, reads to the back cover)
# ----------------------------------------------------------------------
SAMAJA_EDITIONS = {
    "Cuttack": "ct", "Bhubaneswar": "bh", "Sambalpur": "sa",
    "Balasore": "ba", "Berhampur": "br", "Rourkela": "ro",
    "Angul-Dhenkanal": "an", "Koraput": "ko",
}

def fetch_samaja_pages(d: date, edition_code: str):
    session = requests.Session()
    page_num = 1
    while True:
        url = f"https://www.samajaepaper.in/epaperimages////{d.strftime('%d%m%Y')}////{d.strftime('%d%m%Y')}-md-{edition_code}-{page_num}.jpg"
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 2000:
                if page_num > 2: # Safely skip only the front 2 pages
                    yield (page_num, resp.content)
            else: break
        except requests.RequestException: break
        page_num += 1

SAMBAD_EDITIONS = {"Bhubaneswar": "hr"}

def fetch_sambad_pages(d: date, edition_code: str):
    session = requests.Session()
    page_num = 1
    while True:
        url = f"https://sambadepaper.com/epaperimages//{d.strftime('%d%m%Y')}//{d.strftime('%d%m%Y')}-md-{edition_code}-{page_num}ss.jpg"
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 2000:
                if page_num > 2:
                    yield (page_num, resp.content)
            else: break
        except requests.RequestException: break
        page_num += 1

DHARITRI_EDITIONS = {
    "Bhubaneswar": (4, "bhubaneswar"), "Sambalpur": (5, "sambalpur"),
    "Berhampur": (6, "berhampur"), "Angul-Dhenkanal": (7, "angul-dhenkanal"),
    "Balasore": (8, "balasore"), "Rayagada": (9, "rayagada"), "Upakula": (10, "upakula-odisha"),
}

def fetch_dharitri_pages(d: date, edition_tuple):
    city_id, slug = edition_tuple
    session = requests.Session()
    eid = None
    
    for listing_page in range(1, 3):
        suffix = f"/page/{listing_page}" if listing_page > 1 else ""
        url = f"https://dharitriepaper.in/category/{city_id}/{slug}{suffix}"
        try:
            resp = session.get(url, timeout=10)
            if resp.status_code != 200: continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=re.compile(rf"/edition/(\d+)/{re.escape(slug)}$")):
                m = re.search(r"/edition/(\d+)/", a["href"])
                if not m: continue
                temp_eid = m.group(1)
                node = a
                date_match = None
                for _ in range(4):
                    if not node.parent: break
                    node = node.parent
                    date_match = re.search(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", node.get_text(" ", strip=True))
                    if date_match: break
                if date_match:
                    try:
                        if datetime.strptime(date_match.group(0), "%b %d, %Y").date() == d:
                            eid = temp_eid; break
                    except ValueError: continue
            if eid: break
        except requests.RequestException: pass
    
    if not eid: return
    
    try:
        resp = session.get(f"https://dharitriepaper.in/edition/{eid}/{slug}", timeout=10)
        if resp.status_code != 200: return
        raw_matches = re.findall(r'imageprocessor\?image=([^&"]+)', resp.text)
        seen, ordered_urls = set(), []
        for enc in raw_matches:
            real_url = urllib.parse.unquote(enc)
            if real_url not in seen and real_url.lower().endswith((".jpg", ".jpeg", ".png")):
                seen.add(real_url); ordered_urls.append(real_url)
        
        # Skip only the first 2 pages
        if len(ordered_urls) > 2: ordered_urls = ordered_urls[2:]
            
        for i, img_url in enumerate(ordered_urls, start=3):
            try:
                r2 = session.get(img_url, timeout=10)
                if r2.status_code == 200 and len(r2.content) > 2000:
                    yield (i, r2.content)
            except requests.RequestException: continue
    except requests.RequestException: return

def fetch_prameya_pages(d: date, edition_code: str):
    session = requests.Session()
    try:
        resp = session.get("https://www.prameyaepaper.com/", timeout=10)
        matches = re.findall(r'https://img\.prameyaepaper\.com/FilesUpload/[^"\']+\.webp', resp.text)
        urls = list(dict.fromkeys(matches))
        
        # Skip only the first 2 pages
        if len(urls) > 2: urls = urls[2:]
            
        for i, img_url in enumerate(urls, start=3):
            try:
                r2 = session.get(img_url, timeout=10)
                if r2.status_code == 200 and len(r2.content) > 2000:
                    yield (i, r2.content)
            except requests.RequestException: continue
    except requests.RequestException: return

PAPERS = {
    "Samaja":   {"editions": SAMAJA_EDITIONS,   "fetch": fetch_samaja_pages,   "ready": True},
    "Sambad":   {"editions": SAMBAD_EDITIONS,   "fetch": fetch_sambad_pages,   "ready": True},
    "Dharitri": {"editions": DHARITRI_EDITIONS, "fetch": fetch_dharitri_pages, "ready": True},
    "Prameya":  {"editions": {"Bhubaneswar": "bbsr"}, "fetch": fetch_prameya_pages, "ready": True},
}

ALL_CITIES = list(set([city for p in PAPERS.values() for city in p["editions"].keys()]))

# ----------------------------------------------------------------------
# 4. HIGH-RESOLUTION OCR (Memory Safe, Huge Cropping)
# ----------------------------------------------------------------------
OCR_CONFIG = "--oem 1 --psm 3"
MAX_OCR_WIDTH = 1600  # HIGH RESOLUTION restored to catch tiny tender text!

def process_page(paper, page_num, image_bytes, edition_choice, selected_date):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    
    if img.width > MAX_OCR_WIDTH:
        scale = MAX_OCR_WIDTH / img.width
        small = img.resize((MAX_OCR_WIDTH, int(img.height * scale)), Image.LANCZOS)
    else:
        scale = 1.0
        small = img

    enhancer = ImageEnhance.Contrast(small)
    small = enhancer.enhance(1.8)

    text_upper = pytesseract.image_to_string(small, lang="eng", config=OCR_CONFIG).upper()
    tender_hits = [w for w in TENDER_WORDS if w in text_upper]
    service_hits = [w for w in SERVICE_WORDS if w in text_upper]
    
    # Improved match logic: Flag if it mentions BOTH, or strongly hits your domain (service_hits)
    matched = bool(tender_hits and service_hits) or bool(service_hits)

    crop_img = None
    if matched:
        data = pytesseract.image_to_data(small, lang="eng", config=OCR_CONFIG, output_type=Output.DICT)
        
        xs1, ys1, xs2, ys2 = [], [], [], []
        n = len(data.get("text", []))
        keywords = tender_hits + service_hits
        for i in range(n):
            word = (data["text"][i] or "").strip().upper()
            if not word: continue
            if any(k in word or word in k for k in keywords if len(k) <= 20):
                x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                xs1.append(x); ys1.append(y); xs2.append(x + w); ys2.append(y + h)
        
        if xs1:
            inv = 1 / scale
            # MASSIVE PADDING added to grab the entire surrounding tender box!
            left = max(int(min(xs1) * inv) - 250, 0)
            top = max(int(min(ys1) * inv) - 450, 0)
            right = min(int(max(xs2) * inv) + 250, img.width)
            bottom = min(int(max(ys2) * inv) + 900, img.height)
            crop_img = img.crop((left, top, right, bottom)) if (right - left > 100) else img
        else:
            crop_img = img

    thumb = img.copy()
    thumb.thumbnail((250, 250))
    
    return {
        "paper": paper, "page": page_num, "matched": matched, 
        "tender_hits": sorted(set(tender_hits)), "service_hits": sorted(set(service_hits)),
        "full_img": img, "crop_img": crop_img, "thumb": thumb,
    }

def run_search(selected_papers, selected_date, edition_choice, progress_cb):
    jobs = []
    for paper in selected_papers:
        if not PAPERS[paper]["ready"]: continue
        code = PAPERS[paper]["editions"].get(edition_choice)
        if not code: continue
        
        generator = PAPERS[paper]["fetch"](selected_date, code)
        for page_num, content in generator:
            jobs.append((paper, page_num, content))

    results = []
    if not jobs: return []

    total_jobs = len(jobs)
    for i, (paper, page_num, content) in enumerate(jobs):
        try:
            res = process_page(paper, page_num, content, edition_choice, selected_date)
            results.append(res)
        except Exception: pass
        finally:
            del content
            gc.collect() # Force server to dump memory after EVERY single page!
            
        progress_cb((i + 1) / total_jobs)

    return results

# ----------------------------------------------------------------------
# 5. WHATSAPP MODULE
# ----------------------------------------------------------------------
def share_button(img: Image.Image, key: str):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode()
    
    html = f"""
    <button id="btn_{key}" style="width:100%; padding:14px; background:#25D366; color:white; font-size: 1.1rem; font-weight: 800; border:none; border-radius:10px; cursor:pointer; box-shadow: 0 4px 10px rgba(37, 211, 102, 0.4);">
        📲 DISPATCH TO WHATSAPP
    </button>
    <script>
    document.getElementById("btn_{key}").onclick = async () => {{
        const b64 = "{b64}";
        const byteString = atob(b64);
        const array = new Uint8Array(byteString.length);
        for(let i=0; i<byteString.length; i++) array[i] = byteString.charCodeAt(i);
        const file = new File([array], "executive_tender.jpg", {{type: "image/jpeg"}});
        if(navigator.share) {{
            await navigator.share({{files: [file], title: "Executive Security Match"}});
        }}
    }};
    </script>
    """
    components.html(html, height=70)

# ----------------------------------------------------------------------
# 6. DASHBOARD RENDER LOGIC
# ----------------------------------------------------------------------
if "results" not in st.session_state: st.session_state.results = None
if "dismissed" not in st.session_state: st.session_state.dismissed = set()

col1, col2, col3 = st.columns([1,2,1])
with col1:
    selected_date = st.date_input("🗓️ PUBLICATION DATE", value=date.today())
with col2:
    selected_papers = st.multiselect("📰 ACTIVE SOURCES", options=list(PAPERS.keys()), default=["Samaja", "Sambad", "Dharitri", "Prameya"])
with col3:
    edition_choice = st.selectbox("📍 REGION FOCUS", options=ALL_CITIES, index=0)

st.markdown("<br>", unsafe_allow_html=True)
go = st.button("🚀 INITIATE EXECUTIVE SCAN", use_container_width=True)

if go:
    st.session_state.dismissed = set()
    progress = st.progress(0.0, text="Establishing connection to data sources...")
    st.session_state.results = run_search(
        selected_papers, selected_date, edition_choice,
        progress_cb=lambda frac: progress.progress(frac, text=f"Executing OCR extraction... {int(frac*100)}% complete"),
    )
    progress.empty()

results = st.session_state.results

if results is not None:
    if len(results) == 0:
        st.info("SCAN COMPLETE. NO ACTIVE DOCUMENTS FOUND FOR THIS DATE/REGION.")
    else:
        matched = [r for r in results if r["matched"]]
        visible_matches = [r for r in matched if (r["paper"], r["page"]) not in st.session_state.dismissed]

        if not visible_matches:
            st.success("✅ DASHBOARD CLEAR. NO RELEVANT CONTRACTS FOUND.")
        else:
            st.warning(f"⚠️ TARGET ACQUIRED: {len(visible_matches)} relevant document(s) detected.")
            for r in visible_matches:
                key = f"{r['paper']}_{r['page']}"
                with st.container(border=True):
                    st.markdown(f"**SOURCE:** {r['paper']} (Page {r['page']}) &nbsp;&nbsp;|&nbsp;&nbsp; **TAGS:** `{', '.join(r['tender_hits'])}`")
                    st.image(r["crop_img"], use_container_width=True)
                    
                    with st.expander("🔍 EXPAND RAW DOCUMENT"):
                        st.image(r["full_img"], use_container_width=True)

                    c1, c2 = st.columns(2)
                    with c1:
                        share_button(r["crop_img"], key)
                    with c2:
                        if st.button("❌ DISMISS LEAD", key=f"reject_{key}", use_container_width=True):
                            st.session_state.dismissed.add((r["paper"], r["page"]))
                            st.rerun()

        st.markdown("<br><hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
        with st.expander(f"⚙️ SYSTEM LOG: {len(results)} PAGES VERIFIED"):
            cols = st.columns(4)
            for i, r in enumerate(results):
                with cols[i % 4]:
                    border = "3px solid #e63946" if r["matched"] else "1px solid rgba(255,255,255,0.1)"
                    st.markdown(f'<div style="border:{border};border-radius:6px;padding:2px;margin-bottom:8px;background:white;">', unsafe_allow_html=True)
                    st.image(r["thumb"], caption=f"{r['paper']} p{r['page']}", use_container_width=True)
                    st.markdown("</div>", unsafe_allow_html=True)
