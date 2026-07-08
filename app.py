import io
import re
import urllib.parse
from datetime import date

import requests
import streamlit as st
from PIL import Image
import pytesseract
from pytesseract import Output

# ----------------------------------------------------------------------
# CONFIG: keywords we're hunting for
# ----------------------------------------------------------------------
TENDER_WORDS = [
    "TENDER", "CORRIGENDUM", "NIT", "NOTICE INVITING TENDER",
    "E-TENDER", "E TENDER", "EXPRESSION OF INTEREST", "EOI",
]
SERVICE_WORDS = [
    "SECURITY", "HOUSEKEEPING", "HOUSE KEEPING", "MANPOWER",
    "WATCHMAN", "WATCHMEN", "GUARD", "GUARDS", "OUTSOURC",
    "FACILITY MANAGEMENT", "SECURITY GUARD", "SECURITY PERSONNEL",
]

# ----------------------------------------------------------------------
# SAMAJA: fully working. Direct image URLs, predictable by date.
# ----------------------------------------------------------------------
SAMAJA_EDITIONS = {
    "Cuttack": "ct",
    "Bhubaneswar": "bh",
    "Sambalpur": "sa",
    "Balasore": "ba",
    "Berhampur": "br",
    "Rourkela": "ro",
    "Angul": "an",
    "Koraput": "ko",
}

def samaja_page_url(d: date, edition_code: str, page: int) -> str:
    ddmmyyyy = d.strftime("%d%m%Y")
    return (
        f"https://www.samajaepaper.in/epaperimages////{ddmmyyyy}////"
        f"{ddmmyyyy}-md-{edition_code}-{page}.jpg"
    )

def fetch_samaja_pages(d: date, edition_code: str, max_pages: int = 12):
    session = requests.Session()
    for page in range(1, max_pages + 1):
        url = samaja_page_url(d, edition_code, page)
        try:
            resp = session.get(url, timeout=15)
        except requests.RequestException:
            break
        if resp.status_code != 200 or len(resp.content) < 2000:
            break
        try:
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        except Exception:
            break
        yield page, img

# ----------------------------------------------------------------------
# SAMBAD: fully working. Direct image URLs, predictable by date.
# ----------------------------------------------------------------------
SAMBAD_EDITIONS = {
    "Bhubaneswar": "hr",
}

def sambad_page_url(d: date, edition_code: str, page: int) -> str:
    ddmmyyyy = d.strftime("%d%m%Y")
    return (
        f"https://sambadepaper.com/epaperimages//{ddmmyyyy}//"
        f"{ddmmyyyy}-md-{edition_code}-{page}ss.jpg"
    )

def fetch_sambad_pages(d: date, edition_code: str, max_pages: int = 12):
    session = requests.Session()
    for page in range(1, max_pages + 1):
        url = sambad_page_url(d, edition_code, page)
        try:
            resp = session.get(url, timeout=15)
        except requests.RequestException:
            break
        if resp.status_code != 200 or len(resp.content) < 2000:
            break
        try:
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        except Exception:
            break
        yield page, img

# ----------------------------------------------------------------------
# DHARITRI / PRAMEYA: Web scraping for daily hashes
# ----------------------------------------------------------------------
def fetch_dharitri_pages(d: date, edition_code: str, max_pages: int = 12):
    session = requests.Session()
    try:
        # Fetch the main page HTML
        resp = session.get("https://dharitriepaper.in/", timeout=15)
        
        # Search the HTML for the hashed image links
        matches = re.findall(r'https?%3A%2F%2Fdharitriepaper\.in%2Fuploads%2Fepaper%2F[^&"\']+', resp.text)
        matches += re.findall(r'https?://dharitriepaper\.in/uploads/epaper/[^"\']+', resp.text)
        
        # Clean and remove duplicates
        image_urls = []
        for m in set(matches):
            clean_url = urllib.parse.unquote(m)
            if clean_url not in image_urls:
                image_urls.append(clean_url)
        
        # Download the images
        for page, img_url in enumerate(image_urls[:max_pages], start=1):
            img_resp = session.get(img_url, timeout=15)
            if img_resp.status_code == 200:
                img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
                yield page, img
    except Exception as e:
        st.error(f"Error fetching Dharitri: {e}")

def fetch_prameya_pages(d: date, edition_code: str, max_pages: int = 15):
    session = requests.Session()
    try:
        # Fetch the main page HTML
        resp = session.get("https://www.prameyaepaper.com/", timeout=15)
        
        # Search the HTML for the hashed .webp image links
        matches = re.findall(r'https://img\.prameyaepaper\.com/FilesUpload/[^"\']+\.webp', resp.text)
        
        # Remove duplicates while keeping page order
        image_urls = list(dict.fromkeys(matches))
        
        # Download the images
        for page, img_url in enumerate(image_urls[:max_pages], start=1):
            img_resp = session.get(img_url, timeout=15)
            if img_resp.status_code == 200:
                img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
                yield page, img
    except Exception as e:
        st.error(f"Error fetching Prameya: {e}")

PAPERS = {
    "Samaja": {"editions": SAMAJA_EDITIONS, "fetch": fetch_samaja_pages, "ready": True},
    "Sambad": {"editions": SAMBAD_EDITIONS, "fetch": fetch_sambad_pages, "ready": True},
    "Dharitri": {"editions": {"Bhubaneswar": "bbsr"}, "fetch": fetch_dharitri_pages, "ready": True},
    "Prameya": {"editions": {"Bhubaneswar": "bbsr"}, "fetch": fetch_prameya_pages, "ready": True},
}

# ----------------------------------------------------------------------
# OCR + matching
# ----------------------------------------------------------------------
def ocr_page(img: Image.Image):
    text = pytesseract.image_to_string(img, lang="eng")
    data = pytesseract.image_to_data(img, lang="eng", output_type=Output.DICT)
    return text.upper(), data

def find_matches(text_upper: str):
    hit_tender = [w for w in TENDER_WORDS if w in text_upper]
    hit_service = [w for w in SERVICE_WORDS if w in text_upper]
    if hit_tender and hit_service:
        return hit_tender, hit_service
    return None, None

def crop_around_keywords(img: Image.Image, data: dict, keywords: list, padding: int = 80):
    xs1, ys1, xs2, ys2 = [], [], [], []
    n = len(data.get("text", []))
    for i in range(n):
        word = (data["text"][i] or "").strip().upper()
        if not word:
            continue
        if any(k in word or word in k for k in keywords if len(k) <= 20):
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            xs1.append(x)
            ys1.append(y)
            xs2.append(x + w)
            ys2.append(y + h)
    if not xs1:
        return img  
    left = max(min(xs1) - padding, 0)
    top = max(min(ys1) - padding * 3, 0)
    right = min(max(xs2) + padding, img.width)
    bottom = min(max(ys2) + padding * 3, img.height)
    if right - left < 100 or bottom - top < 100:
        return img
    return img.crop((left, top, right, bottom))

# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------
st.set_page_config(page_title="Odisha Tender Finder", page_icon="📰", layout="centered")
st.title("📰 Odisha Newspaper Tender Finder")
st.caption(
    "Scans today's Odia e-papers for English tender / corrigendum notices "
    "about security, housekeeping, manpower, or watchman agencies."
)

col1, col2 = st.columns(2)
with col1:
    selected_date = st.date_input("Edition date", value=date.today())
with col2:
    selected_papers = st.multiselect(
        "Newspapers",
        options=list(PAPERS.keys()),
        default=["Samaja", "Sambad", "Dharitri", "Prameya"],
    )

edition_choice = st.selectbox("Edition (city)", options=list(SAMAJA_EDITIONS.keys()), index=1)

not_ready = [p for p in selected_papers if not PAPERS[p]["ready"]]
if not_ready:
    st.warning(
        f"{', '.join(not_ready)} isn't connected yet. It'll be added once its page-link pattern is confirmed."
    )

go = st.button("🔍 Search for Tenders", type="primary", use_container_width=True)

if go:
    any_results = False
    for paper in selected_papers:
        info = PAPERS[paper]
        if not info["ready"]:
            continue
        edition_code = info["editions"].get(edition_choice)
        if edition_code is None:
            st.info(f"{paper} doesn't have a '{edition_choice}' edition — skipping.")
            continue

        st.subheader(f"{paper} — {edition_choice} — {selected_date.strftime('%d %b %Y')}")
        progress = st.progress(0.0, text="Starting…")
        pages_checked = 0
        found_any_for_paper = False

        pages = list(info["fetch"](selected_date, edition_code))
        total = len(pages) if pages else 1

        for idx, (page_num, img) in enumerate(pages, start=1):
            progress.progress(idx / total, text=f"Reading page {page_num}…")
            try:
                text_upper, data = ocr_page(img)
            except Exception as e:
                st.error(f"Couldn't read page {page_num}: {e}")
                continue
            pages_checked += 1
            tender_hits, service_hits = find_matches(text_upper)
            if tender_hits:
                found_any_for_paper = True
                any_results = True
                crop = crop_around_keywords(img, data, tender_hits + service_hits)
                st.image(
                    crop,
                    caption=(
                        f"Page {page_num} — matched: "
                        f"{', '.join(sorted(set(tender_hits)))} + "
                        f"{', '.join(sorted(set(service_hits)))}"
                    ),
                    use_container_width=True,
                )
                buf = io.BytesIO()
                crop.save(buf, format="JPEG", quality=92)
                st.download_button(
                    "⬇️ Save this image (then share to WhatsApp)",
                    data=buf.getvalue(),
                    file_name=f"{paper}_{edition_choice}_{selected_date}_p{page_num}.jpg",
                    mime="image/jpeg",
                    key=f"dl_{paper}_{page_num}",
                )
                with st.expander("Also view the full page (in case the crop missed something)"):
                    st.image(img, use_container_width=True)

        progress.empty()
        if not found_any_for_paper:
            st.info(f"No tender/corrigendum matches found in {paper} ({pages_checked} pages checked).")

    if not any_results:
        st.success("Done. No matching notices today in the papers you selected.")
else:
    st.write("Pick a date and press the button above to start.")

st.divider()
st.caption(
    "Tip: OCR isn't perfect on newsprint scans — if you know a tender was published "
    "today but nothing was flagged, it's worth a quick manual look at the classified "
    "pages too, just this once in a while, to sanity-check the tool."
)
