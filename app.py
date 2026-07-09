import base64
import io
import re
import urllib.parse
from datetime import date, datetime

import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from PIL import Image
import pytesseract
from pytesseract import Output

# ----------------------------------------------------------------------
# BRANDING & CSS INJECTION (Must be the first Streamlit command)
# ----------------------------------------------------------------------
st.set_page_config(page_title="Executive Security | Tender Desk", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
    /* Corporate Branding CSS */
    .stApp { background-color: #f4f6f9; }
    .block-container { padding-top: 2rem; max-width: 1000px;}
    .company-title { font-family: 'Arial Black', sans-serif; color: #0f2d52; font-size: 2.8rem; text-align: center; margin-bottom: 0px; padding-bottom: 0px; letter-spacing: -1px;}
    .company-subtitle { color: #cc1016; font-weight: bold; text-align: center; font-size: 1.1rem; margin-top: 0px; margin-bottom: 2.5rem; letter-spacing: 2px;}
    
    /* Button styling */
    div.stButton > button:first-child { background-color: #0f2d52; color: #ffffff; font-weight: bold; border-radius: 6px; border: none; padding: 0.5rem 1rem;}
    div.stButton > button:first-child:hover { background-color: #cc1016; color: white;}
    
    /* Card styling */
    div[data-testid="stExpander"] { background-color: white; border-radius: 8px; border: 1px solid #e0e0e0; }
</style>
""", unsafe_allow_html=True)

st.markdown("<div class='company-title'>EXECUTIVE SECURITY SERVICE</div>", unsafe_allow_html=True)
st.markdown("<div class='company-subtitle'>AUTOMATED TENDER INTELLIGENCE DESK</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------------
# CONFIG: expanded keywords for government & private outsourcing
# ----------------------------------------------------------------------
TENDER_WORDS = [
    "TENDER", "CORRIGENDUM", "NIT", "NOTICE INVITING TENDER",
    "E-TENDER", "E TENDER", "EXPRESSION OF INTEREST", "EOI",
    "RFP", "REQUEST FOR PROPOSAL", "RFQ", "REQUEST FOR QUOTATION",
    "INVITATION FOR BIDS", "INVITATION OF BIDS", "IFB",
    "ADDENDUM", "TENDER CALL NOTICE", "AWARD OF CONTRACT",
    "SELECTION OF AGENCY", "EMPANELMENT", "BID DOCUMENT",
    "SELECTION OF AGENCY FOR PROVIDING COMPREHENSIVE FACILITY MANAGEMENT SERVICES",
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
# NEWSPAPER LOGIC
# ----------------------------------------------------------------------
SAMAJA_EDITIONS = {
    "Cuttack": "ct", "Bhubaneswar": "bh", "Sambalpur": "sa",
    "Balasore": "ba", "Berhampur": "br", "Rourkela": "ro",
    "Angul-Dhenkanal": "an", "Koraput": "ko",
}

def samaja_page_url(d: date, edition_code: str, page: int) -> str:
    ddmmyyyy = d.strftime("%d%m%Y")
    return f"https://www.samajaepaper.in/epaperimages////{ddmmyyyy}////{ddmmyyyy}-md-{edition_code}-{page}.jpg"

def fetch_samaja_pages(d: date, edition_code: str, max_pages: int = 24):
    session = requests.Session()
    out = []
    for page in range(1, max_pages + 1):
        url = samaja_page_url(d, edition_code, page)
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200 or len(resp.content) < 2000: break
            out.append((page, resp.content))
        except requests.RequestException: break
    return out

SAMBAD_EDITIONS = {"Bhubaneswar": "hr"}

def sambad_page_url(d: date, edition_code: str, page: int) -> str:
    ddmmyyyy = d.strftime("%d%m%Y")
    return f"https://sambadepaper.com/epaperimages//{ddmmyyyy}//{ddmmyyyy}-md-{edition_code}-{page}ss.jpg"

def fetch_sambad_pages(d: date, edition_code: str, max_pages: int = 24):
    session = requests.Session()
    out = []
    for page in range(1, max_pages + 1):
        url = sambad_page_url(d, edition_code, page)
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200 or len(resp.content) < 2000: break
            out.append((page, resp.content))
        except requests.RequestException: break
    return out

DHARITRI_EDITIONS = {
    "Bhubaneswar": (4, "bhubaneswar"), "Sambalpur": (5, "sambalpur"),
    "Berhampur": (6, "berhampur"), "Angul-Dhenkanal": (7, "angul-dhenkanal"),
    "Balasore": (8, "balasore"), "Rayagada": (9, "rayagada"), "Upakula": (10, "upakula-odisha"),
}

def _find_dharitri_edition_id(d: date, city_id: int, slug: str, session, max_listing_pages: int = 6):
    for listing_page in range(1, max_listing_pages + 1):
        url = f"https://dharitriepaper.in/category/{city_id}/{slug}"
        if listing_page > 1: url += f"/page/{listing_page}"
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200: return None
            soup = BeautifulSoup(resp.text, "html.parser")
            links = soup.find_all("a", href=re.compile(rf"/edition/(\d+)/{re.escape(slug)}$"))
            seen_ids = set()
            for a in links:
                m = re.search(r"/edition/(\d+)/", a["href"])
                if not m: continue
                eid = m.group(1)
                if eid in seen_ids: continue
                seen_ids.add(eid)
                node = a
                date_match = None
                for _ in range(4):
                    if not node.parent: break
                    node = node.parent
                    text = node.get_text(" ", strip=True)
                    date_match = re.search(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", text)
                    if date_match: break
                if not date_match: continue
                try:
                    parsed = datetime.strptime(date_match.group(0), "%b %d, %Y").date()
                    if parsed == d: return eid
                except ValueError: continue
            if not links: break
        except requests.RequestException: return None
    return None

def fetch_dharitri_pages(d: date, edition_tuple, max_pages: int = 24):
    city_id, slug = edition_tuple
    session = requests.Session()
    eid = _find_dharitri_edition_id(d, city_id, slug, session)
    if eid is None: return []
    edition_url = f"https://dharitriepaper.in/edition/{eid}/{slug}"
    try:
        resp = session.get(edition_url, timeout=20)
        if resp.status_code != 200: return []
        raw_matches = re.findall(r'imageprocessor\?image=([^&"]+)', resp.text)
        seen, ordered_urls = set(), []
        for enc in raw_matches:
            real_url = urllib.parse.unquote(enc)
            if real_url not in seen and real_url.lower().endswith((".jpg", ".jpeg", ".png")):
                seen.add(real_url)
                ordered_urls.append(real_url)
        out = []
        for i, img_url in enumerate(ordered_urls[:max_pages], start=1):
            try:
                r2 = session.get(img_url, timeout=20)
                if r2.status_code == 200 and len(r2.content) > 2000:
                    out.append((i, r2.content))
            except requests.RequestException: continue
        return out
    except requests.RequestException: return []

def fetch_prameya_pages(d, edition_code):
    return []

PAPERS = {
    "Samaja":   {"editions": SAMAJA_EDITIONS,   "fetch": fetch_samaja_pages,   "ready": True},
    "Sambad":   {"editions": SAMBAD_EDITIONS,   "fetch": fetch_sambad_pages,   "ready": True},
    "Dharitri": {"editions": DHARITRI_EDITIONS, "fetch": fetch_dharitri_pages, "ready": True},
    "Prameya":  {"editions": {},                "fetch": fetch_prameya_pages,  "ready": False},
}

ALL_CITIES = []
for _info in PAPERS.values():
    for _city in _info["editions"]:
        if _city not in ALL_CITIES: ALL_CITIES.append(_city)

# ----------------------------------------------------------------------
# OCR PIPELINE (Sequential - Fixes the Memory Crash!)
# ----------------------------------------------------------------------
OCR_CONFIG = "--oem 1 --psm 6"
MAX_OCR_WIDTH = 1500  

def process_page(paper, page_num, image_bytes, edition_choice, selected_date):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if img.width > MAX_OCR_WIDTH:
        scale = MAX_OCR_WIDTH / img.width
        small = img.resize((MAX_OCR_WIDTH, int(img.height * scale)), Image.LANCZOS)
    else:
        scale = 1.0
        small = img

    text_upper = pytesseract.image_to_string(small, lang="eng", config=OCR_CONFIG).upper()
    tender_hits = [w for w in TENDER_WORDS if w in text_upper]
    service_hits = [w for w in SERVICE_WORDS if w in text_upper]
    matched = bool(tender_hits and service_hits)

    crop_img = None
    if matched:
        data = pytesseract.image_to_data(small, lang="eng", config=OCR_CONFIG, output_type=Output.DICT)
        crop_img = crop_around_keywords(img, data, tender_hits + service_hits, scale)

    thumb = img.copy()
    thumb.thumbnail((220, 220))
    return {
        "paper": paper, "edition": edition_choice, "date": selected_date, "page": page_num,
        "matched": matched, "tender_hits": sorted(set(tender_hits)), "service_hits": sorted(set(service_hits)),
        "full_img": img, "crop_img": crop_img, "thumb": thumb,
    }

def crop_around_keywords(img: Image.Image, data: dict, keywords: list, scale: float, padding: int = 80):
    xs1, ys1, xs2, ys2 = [], [], [], []
    n = len(data.get("text", []))
    for i in range(n):
        word = (data["text"][i] or "").strip().upper()
        if not word: continue
        if any(k in word or word in k for k in keywords if len(k) <= 20):
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            xs1.append(x); ys1.append(y); xs2.append(x + w); ys2.append(y + h)
    if not xs1: return img
    inv = 1 / scale
    left, top = max(int(min(xs1) * inv) - padding, 0), max(int(min(ys1) * inv) - padding * 3, 0)
    right, bottom = min(int(max(xs2) * inv) + padding, img.width), min(int(max(ys2) * inv) + padding * 3, img.height)
    if right - left < 100 or bottom - top < 100: return img
    return img.crop((left, top, right, bottom))

def run_search(selected_papers, selected_date, edition_choice, progress_cb):
    jobs = []
    for paper in selected_papers:
        info = PAPERS[paper]
        if not info["ready"]: continue
        code = info["editions"].get(edition_choice)
        if code is None: continue
        pages = info["fetch"](selected_date, code)
        for page_num, content in pages:
            jobs.append((paper, page_num, content))

    results = []
    if not jobs: return []

    # Replaced ThreadPoolExecutor with a stable, single-file loop to prevent memory crashes!
    total_jobs = len(jobs)
    for i, (paper, page_num, content) in enumerate(jobs):
        try:
            res = process_page(paper, page_num, content, edition_choice, selected_date)
            results.append(res)
        except Exception:
            pass
        progress_cb((i + 1) / total_jobs)

    results.sort(key=lambda r: (r["paper"], r["page"]))
    return results

# ----------------------------------------------------------------------
# WhatsApp Sharing
# ----------------------------------------------------------------------
def share_button(img: Image.Image, key: str):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode()
    html = f"""
    <div style="text-align:center;">
      <button id="share_{key}" style="
        padding:10px 18px;background:#25D366;color:white;border:none;
        border-radius:6px;font-size:15px;cursor:pointer;width:100%;font-weight:bold;">
        📲 Send to WhatsApp
      </button>
      <div id="msg_{key}" style="font-size:12px;color:#888;margin-top:4px;"></div>
    </div>
    <script>
    (function() {{
      const b64 = "{b64}";
      async function doShare() {{
        try {{
          const byteChars = atob(b64);
          const bytes = new Uint8Array(byteChars.length);
          for (let i = 0; i < byteChars.length; i++) {{ bytes[i] = byteChars.charCodeAt(i); }}
          const file = new File([bytes], "tender.jpg", {{ type: "image/jpeg" }});
          if (navigator.canShare && navigator.canShare({{ files: [file] }})) {{
            await navigator.share({{ files: [file], title: "Tender notice" }});
          }} else {{
            document.getElementById("msg_{key}").innerText = "Sharing isn't supported on this device. Use download button.";
          }}
        }} catch (e) {{}}
      }}
      document.getElementById("share_{key}").addEventListener("click", doShare);
    }})();
    </script>
    """
    components.html(html, height=70)

# ----------------------------------------------------------------------
# UI Logic
# ----------------------------------------------------------------------
if "results" not in st.session_state: st.session_state.results = None
if "dismissed" not in st.session_state: st.session_state.dismissed = set()

with st.container(border=True):
    col1, col2, col3 = st.columns([1,2,1])
    with col1:
        selected_date = st.date_input("Date", value=date.today())
    with col2:
        selected_papers = st.multiselect("Active Sources", options=list(PAPERS.keys()), default=["Samaja", "Sambad", "Dharitri"])
    with col3:
        edition_choice = st.selectbox("Region", options=ALL_CITIES, index=0)

    go = st.button("🚀 INITIATE SCAN", use_container_width=True)

if go:
    st.session_state.dismissed = set()
    progress = st.progress(0.0, text="System initializing...")
    st.session_state.results = run_search(
        selected_papers, selected_date, edition_choice,
        progress_cb=lambda frac: progress.progress(frac, text=f"Processing documents... {int(frac*100)}% complete"),
    )
    progress.empty()

results = st.session_state.results

if results is not None:
    if len(results) == 0:
        st.info("Scan complete. No active documents found for this criteria.")
    else:
        matched = [r for r in results if r["matched"]]
        visible_matches = [r for r in matched if (r["paper"], r["page"]) not in st.session_state.dismissed]

        if not visible_matches:
            st.success("✅ Dashboard Clear. No relevant tenders found today.")
        else:
            st.error(f"⚠️ Alert: {len(visible_matches)} relevant document(s) detected.")
            for r in visible_matches:
                key = f"{r['paper']}_{r['page']}"
                with st.container(border=True):
                    st.markdown(f"**SOURCE:** {r['paper']} (Page {r['page']}) | **TAGS:** `{', '.join(r['tender_hits'])}`")
                    st.image(r["crop_img"], use_container_width=True)
                    
                    with st.expander("Expand Full Document"):
                        st.image(r["full_img"], use_container_width=True)

                    c1, c2 = st.columns(2)
                    with c1:
                        share_button(r["crop_img"], key)
                    with c2:
                        if st.button("❌ Dismiss", key=f"reject_{key}", use_container_width=True):
                            st.session_state.dismissed.add((r["paper"], r["page"]))
                            st.rerun()

        with st.expander(f"System Log: {len(results)} pages scanned"):
            cols = st.columns(4)
            for i, r in enumerate(results):
                with cols[i % 4]:
                    border = "3px solid #cc1016" if r["matched"] else "1px solid #e0e0e0"
                    st.markdown(f'<div style="border:{border};border-radius:6px;padding:2px;margin-bottom:8px;">', unsafe_allow_html=True)
                    st.image(r["thumb"], caption=f"{r['paper']} p{r['page']}", use_container_width=True)
                    st.markdown("</div>", unsafe_allow_html=True)
