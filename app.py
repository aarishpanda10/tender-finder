import io
import re
import urllib.parse
from datetime import date

import requests
import streamlit as st
from PIL import Image, ImageEnhance
import pytesseract
from pytesseract import Output

# ----------------------------------------------------------------------
# CONFIG: keywords we're hunting for
# ----------------------------------------------------------------------
TENDER_WORDS = [
    "TENDER", "CORRIGENDUM", "NIT", "NOTICE INVITING TENDER",
    "E-TENDER", "E TENDER", "EXPRESSION OF INTEREST", "EOI",
    "RFP", "REQUEST FOR PROPOSAL"
]
SERVICE_WORDS = [
    "SECURITY", "HOUSEKEEPING", "HOUSE KEEPING", "MANPOWER",
    "WATCHMAN", "WATCHMEN", "GUARD", "GUARDS", "OUTSOURC",
    "FACILITY MANAGEMENT", "SECURITY GUARD", "SECURITY PERSONNEL",
]

# ----------------------------------------------------------------------
# STATE MANAGEMENT (Crucial for Accept/Reject buttons)
# ----------------------------------------------------------------------
if 'search_completed' not in st.session_state:
    st.session_state.search_completed = False
if 'found_matches' not in st.session_state:
    st.session_state.found_matches = []

# ----------------------------------------------------------------------
# NEWSPAPER FETCHING LOGIC (Defaults to 24 pages for deep scans)
# ----------------------------------------------------------------------
SAMAJA_EDITIONS = {
    "Cuttack": "ct", "Bhubaneswar": "bh", "Sambalpur": "sa",
    "Balasore": "ba", "Berhampur": "br", "Rourkela": "ro",
    "Angul": "an", "Koraput": "ko",
}
SAMBAD_EDITIONS = {"Bhubaneswar": "hr"}

def samaja_page_url(d: date, edition_code: str, page: int) -> str:
    ddmmyyyy = d.strftime("%d%m%Y")
    return f"https://www.samajaepaper.in/epaperimages////{ddmmyyyy}////{ddmmyyyy}-md-{edition_code}-{page}.jpg"

def fetch_samaja_pages(d: date, edition_code: str, max_pages: int = 24):
    session = requests.Session()
    for page in range(1, max_pages + 1):
        url = samaja_page_url(d, edition_code, page)
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200 or len(resp.content) < 2000: break
            yield page, Image.open(io.BytesIO(resp.content)).convert("RGB")
        except Exception: break

def sambad_page_url(d: date, edition_code: str, page: int) -> str:
    ddmmyyyy = d.strftime("%d%m%Y")
    return f"https://sambadepaper.com/epaperimages//{ddmmyyyy}//{ddmmyyyy}-md-{edition_code}-{page}ss.jpg"

def fetch_sambad_pages(d: date, edition_code: str, max_pages: int = 24):
    session = requests.Session()
    for page in range(1, max_pages + 1):
        url = sambad_page_url(d, edition_code, page)
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200 or len(resp.content) < 2000: break
            yield page, Image.open(io.BytesIO(resp.content)).convert("RGB")
        except Exception: break

def fetch_dharitri_pages(d: date, edition_code: str, max_pages: int = 24):
    session = requests.Session()
    try:
        resp = session.get("https://dharitriepaper.in/", timeout=15)
        matches = re.findall(r'https?%3A%2F%2Fdharitriepaper\.in%2Fuploads%2Fepaper%2F[^&"\']+', resp.text)
        matches += re.findall(r'https?://dharitriepaper\.in/uploads/epaper/[^"\']+', resp.text)
        
        image_urls = []
        for m in set(matches):
            clean_url = urllib.parse.unquote(m)
            if clean_url not in image_urls: image_urls.append(clean_url)
            
        for page, img_url in enumerate(image_urls[:max_pages], start=1):
            img_resp = session.get(img_url, timeout=15)
            if img_resp.status_code == 200:
                yield page, Image.open(io.BytesIO(img_resp.content)).convert("RGB")
    except Exception as e:
        st.error(f"Error fetching Dharitri: {e}")

def fetch_prameya_pages(d: date, edition_code: str, max_pages: int = 24):
    session = requests.Session()
    try:
        resp = session.get("https://www.prameyaepaper.com/", timeout=15)
        matches = re.findall(r'https://img\.prameyaepaper\.com/FilesUpload/[^"\']+\.webp', resp.text)
        image_urls = list(dict.fromkeys(matches))
        
        for page, img_url in enumerate(image_urls[:max_pages], start=1):
            img_resp = session.get(img_url, timeout=15)
            if img_resp.status_code == 200:
                yield page, Image.open(io.BytesIO(img_resp.content)).convert("RGB")
    except Exception as e:
        st.error(f"Error fetching Prameya: {e}")

PAPERS = {
    "Samaja": {"editions": SAMAJA_EDITIONS, "fetch": fetch_samaja_pages, "ready": True},
    "Sambad": {"editions": SAMBAD_EDITIONS, "fetch": fetch_sambad_pages, "ready": True},
    "Dharitri": {"editions": {"Bhubaneswar": "bbsr"}, "fetch": fetch_dharitri_pages, "ready": True},
    "Prameya": {"editions": {"Bhubaneswar": "bbsr"}, "fetch": fetch_prameya_pages, "ready": True},
}

# ----------------------------------------------------------------------
# HIGH-RES OCR & IMAGE CROPPING
# ----------------------------------------------------------------------
def ocr_page(img: Image.Image):
    # digitally zoom 2x so Tesseract can actually read the tiny font
    new_size = (img.width * 2, img.height * 2)
    scaled_img = img.resize(new_size, Image.Resampling.LANCZOS)
    
    enhancer = ImageEnhance.Contrast(scaled_img)
    img_contrast = enhancer.enhance(2.0)
    
    text = pytesseract.image_to_string(img_contrast, lang="eng")
    data = pytesseract.image_to_data(img_contrast, lang="eng", output_type=Output.DICT)
    
    # Return the scaled image so our crops match the new coordinates!
    return text.upper(), data, scaled_img

def find_matches(text_upper: str):
    hit_tender = [w for w in TENDER_WORDS if w in text_upper]
    hit_service = [w for w in SERVICE_WORDS if w in text_upper]
    if (hit_tender and hit_service) or hit_service:
        return hit_tender or ["NOTICE"], hit_service
    return None, None

def crop_around_keywords(img: Image.Image, data: dict, keywords: list):
    xs1, ys1, xs2, ys2 = [], [], [], []
    n = len(data.get("text", []))
    for i in range(n):
        word = (data["text"][i] or "").strip().upper()
        if not word: continue
        if any(k in word or word in k for k in keywords if len(k) <= 20):
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            xs1.append(x); ys1.append(y); xs2.append(x + w); ys2.append(y + h)
            
    if not xs1: return img  
    
    # Doubled the padding because the image is 2x larger now
    left = max(min(xs1) - 400, 0)
    top = max(min(ys1) - 500, 0)
    right = min(max(xs2) + 400, img.width)
    bottom = min(max(ys2) + 1200, img.height)
    
    if right - left < 100 or bottom - top < 100:
        return img
    return img.crop((left, top, right, bottom))

# ----------------------------------------------------------------------
# UI & APPLICATION FLOW (Memory-Safe Loop)
# ----------------------------------------------------------------------
st.set_page_config(page_title="Odisha Tender Finder", page_icon="📰", layout="centered")
st.title("📰 Odisha Newspaper Tender Finder")

col1, col2 = st.columns(2)
with col1:
    selected_date = st.date_input("Edition date", value=date.today())
with col2:
    selected_papers = st.multiselect("Newspapers", options=list(PAPERS.keys()), default=["Samaja", "Sambad", "Dharitri", "Prameya"])
edition_choice = st.selectbox("Edition (city)", options=list(SAMAJA_EDITIONS.keys()), index=1)

if st.button("🔍 Search for Tenders", type="primary", use_container_width=True):
    st.session_state.found_matches = []
    st.session_state.search_completed = False
    
    progress = st.progress(0.0, text="Starting scan...")
    
    for paper in selected_papers:
        info = PAPERS[paper]
        edition_code = info["editions"].get(edition_choice)
        if edition_code is None: continue
        
        max_p = 24
        # Process lazily to save memory!
        pages_generator = info["fetch"](selected_date, edition_code, max_pages=max_p)
        
        for idx, (page_num, img) in enumerate(pages_generator, start=1):
            progress.progress(idx / max_p, text=f"Scanning {paper} - Page {page_num}...")
            try:
                # Use the new high-res scaled image
                text_upper, data, scaled_img = ocr_page(img)
                tender_hits, service_hits = find_matches(text_upper)
                
                if tender_hits:
                    crop = crop_around_keywords(scaled_img, data, tender_hits + service_hits)
                    
                    buf = io.BytesIO()
                    crop.save(buf, format="JPEG", quality=95)
                    img_bytes = buf.getvalue()
                    
                    st.session_state.found_matches.append({
                        "paper": paper,
                        "page": page_num,
                        "crop": crop,
                        "bytes": img_bytes,
                        "filename": f"{paper}_{edition_choice}_{selected_date}_p{page_num}.jpg"
                    })
            except Exception:
                continue
                
    progress.empty()
    st.session_state.search_completed = True
    st.rerun()

# The Review Phase (Accept/Reject UI)
if st.session_state.search_completed:
    if len(st.session_state.found_matches) == 0:
        st.success("Done. No matching notices found in the selected papers.")
    else:
        st.success(f"Found {len(st.session_state.found_matches)} potential tenders!")
        st.divider()
        
        for i, match in enumerate(st.session_state.found_matches):
            st.subheader(f"📄 {match['paper']} — Page {match['page']}")
            st.image(match['crop'], use_container_width=True)
            
            status_key = f"status_{i}"
            if status_key not in st.session_state:
                st.session_state[status_key] = "pending"
                
            if st.session_state[status_key] == "pending":
                c1, c2 = st.columns(2)
                if c1.button("✅ Accept", key=f"acc_{i}", use_container_width=True):
                    st.session_state[status_key] = "accepted"
                    st.rerun()
                if c2.button("❌ Reject", key=f"rej_{i}", use_container_width=True):
                    st.session_state[status_key] = "rejected"
                    st.rerun()
                    
            elif st.session_state[status_key] == "accepted":
                st.info("Status: Accepted")
                st.download_button(
                    "📲 Tap here to Share to WhatsApp", 
                    data=match['bytes'], 
                    file_name=match['filename'], 
                    mime="image/jpeg", 
                    key=f"dl_{i}",
                    use_container_width=True
                )
                
            elif st.session_state[status_key] == "rejected":
                st.warning("Bye 👋 (Rejected)")
                
            st.divider()
