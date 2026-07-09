import base64
import io
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime

import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from PIL import Image
import pytesseract
from pytesseract import Output

# ----------------------------------------------------------------------
# CONFIG: expanded keywords for government & private outsourcing
# A page is flagged only if it contains AT LEAST ONE word from EACH group.
# ----------------------------------------------------------------------
TENDER_WORDS = [
    # Standard Tender Terms
    "TENDER", "CORRIGENDUM", "NIT", "NOTICE INVITING TENDER",
    "E-TENDER", "E TENDER", "EXPRESSION OF INTEREST", "EOI",
    "RFP", "REQUEST FOR PROPOSAL", "RFQ", "REQUEST FOR QUOTATION",

    # Contract & Agency Announcements
    "INVITATION FOR BIDS", "INVITATION OF BIDS", "IFB",
    "ADDENDUM", "TENDER CALL NOTICE", "AWARD OF CONTRACT",
    "SELECTION OF AGENCY", "EMPANELMENT", "BID DOCUMENT",
    "SELECTION OF AGENCY FOR PROVIDING COMPREHENSIVE FACILITY MANAGEMENT SERVICES",
]
SERVICE_WORDS = [
    # Core Security & Facility Management
    "SECURITY", "HOUSEKEEPING", "HOUSE KEEPING", "MANPOWER",
    "WATCHMAN", "WATCHMEN", "GUARD", "GUARDS", "OUTSOURC",  # covers Outsourced / Outsourcing
    "FACILITY MANAGEMENT", "SECURITY GUARD", "SECURITY PERSONNEL",
    "CFMS", "UPKEEPING", "CLEANING", "MAINTENANCE", "SANITATION",

    # Specific Outsourced Roles & Medical Staff
    "SWEEPER", "PEON", "PARAMEDIC", "NURSING", "TECHNO-MANAGERIAL",
    "SUPPORT STAFF", "MULTI TASKING STAFF", "MTS", "DATA ENTRY OPERATOR",
    "DEO", "ATTENDANT", "DRIVER", "WARD BOY", "SERVICE PROVIDER",
]

# ----------------------------------------------------------------------
# SAMAJA: direct image URLs, predictable by date.
# ----------------------------------------------------------------------
SAMAJA_EDITIONS = {
    "Cuttack": "ct", "Bhubaneswar": "bh", "Sambalpur": "sa",
    "Balasore": "ba", "Berhampur": "br", "Rourkela": "ro",
    "Angul-Dhenkanal": "an", "Koraput": "ko",
}

def samaja_page_url(d: date, edition_code: str, page: int) -> str:
    ddmmyyyy = d.strftime("%d%m%Y")
    return (
        f"https://www.samajaepaper.in/epaperimages////{ddmmyyyy}////"
        f"{ddmmyyyy}-md-{edition_code}-{page}.jpg"
    )

def fetch_samaja_pages(d: date, edition_code: str, max_pages: int = 30):
    session = requests.Session()
    out = []
    for page in range(1, max_pages + 1):
        url = samaja_page_url(d, edition_code, page)
        try:
            resp = session.get(url, timeout=15)
        except requests.RequestException:
            break
        if resp.status_code != 200 or len(resp.content) < 2000:
            break
        out.append((page, resp.content))
    return out

# ----------------------------------------------------------------------
# SAMBAD: same style of direct, predictable image URLs as Samaja.
# Only one edition code ("hr") is confirmed so far.
# ----------------------------------------------------------------------
SAMBAD_EDITIONS = {"Bhubaneswar": "hr"}

def sambad_page_url(d: date, edition_code: str, page: int) -> str:
    ddmmyyyy = d.strftime("%d%m%Y")
    return (
        f"https://sambadepaper.com/epaperimages//{ddmmyyyy}//"
        f"{ddmmyyyy}-md-{edition_code}-{page}ss.jpg"
    )

def fetch_sambad_pages(d: date, edition_code: str, max_pages: int = 30):
    session = requests.Session()
    out = []
    for page in range(1, max_pages + 1):
        url = sambad_page_url(d, edition_code, page)
        try:
            resp = session.get(url, timeout=15)
        except requests.RequestException:
            break
        if resp.status_code != 200 or len(resp.content) < 2000:
            break
        out.append((page, resp.content))
    return out

# ----------------------------------------------------------------------
# DHARITRI: page images aren't date-predictable directly. Each date has
# an "edition id" that we have to look up first on the paper's own
# category/listing page, then read the edition page's HTML to collect
# every page's real image URL (hidden inside an "imageprocessor?image="
# wrapper used for thumbnails).
# ----------------------------------------------------------------------
DHARITRI_EDITIONS = {
    "Bhubaneswar": (4, "bhubaneswar"),
    "Sambalpur": (5, "sambalpur"),
    "Berhampur": (6, "berhampur"),
    "Angul-Dhenkanal": (7, "angul-dhenkanal"),
    "Balasore": (8, "balasore"),
    "Rayagada": (9, "rayagada"),
    "Upakula": (10, "upakula-odisha"),
}

def _find_dharitri_edition_id(d: date, city_id: int, slug: str, session, max_listing_pages: int = 6):
    for listing_page in range(1, max_listing_pages + 1):
        url = f"https://dharitriepaper.in/category/{city_id}/{slug}"
        if listing_page > 1:
            url += f"/page/{listing_page}"
        try:
            resp = session.get(url, timeout=15)
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=re.compile(rf"/edition/(\d+)/{re.escape(slug)}$"))
        seen_ids = set()
        for a in links:
            m = re.search(r"/edition/(\d+)/", a["href"])
            if not m:
                continue
            eid = m.group(1)
            if eid in seen_ids:
                continue
            seen_ids.add(eid)
            # walk outward one ancestor at a time and stop at the FIRST
            # level that contains a date — going too far up risks picking
            # up a neighbouring card's date instead of this one's.
            node = a
            date_match = None
            for _ in range(4):
                if not node.parent:
                    break
                node = node.parent
                text = node.get_text(" ", strip=True)
                date_match = re.search(r"[A-Z][a-z]{2} \d{1,2}, \d{4}", text)
                if date_match:
                    break
            if not date_match:
                continue
            try:
                parsed = datetime.strptime(date_match.group(0), "%b %d, %Y").date()
            except ValueError:
                continue
            if parsed == d:
                return eid
        if not links:
            break
    return None

def fetch_dharitri_pages(d: date, edition_tuple, max_pages: int = 40):
    city_id, slug = edition_tuple
    session = requests.Session()
    eid = _find_dharitri_edition_id(d, city_id, slug, session)
    if eid is None:
        return []
    edition_url = f"https://dharitriepaper.in/edition/{eid}/{slug}"
    try:
        resp = session.get(edition_url, timeout=20)
    except requests.RequestException:
        return []
    if resp.status_code != 200:
        return []
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
        except requests.RequestException:
            continue
        if r2.status_code == 200 and len(r2.content) > 2000:
            out.append((i, r2.content))
    return out

# ----------------------------------------------------------------------
# PRAMEYA: not wired up. Its reader uses a tile-based zoomable image
# viewer (like a map viewer) rather than one plain image per page, so
# this needs a different approach — see README.
# ----------------------------------------------------------------------
def fetch_prameya_pages(d, edition_code):
    return []

PAPERS = {
    "Samaja":   {"editions": SAMAJA_EDITIONS,   "fetch": fetch_samaja_pages,   "ready": True},
    "Sambad":   {"editions": SAMBAD_EDITIONS,   "fetch": fetch_sambad_pages,   "ready": True},
    "Dharitri": {"editions": DHARITRI_EDITIONS, "fetch": fetch_dharitri_pages, "ready": True},
    "Prameya":  {"editions": {},                "fetch": fetch_prameya_pages,  "ready": False},
}

# Union of all city names across papers, for one shared dropdown.
ALL_CITIES = []
for _info in PAPERS.values():
    for _city in _info["editions"]:
        if _city not in ALL_CITIES:
            ALL_CITIES.append(_city)

# ----------------------------------------------------------------------
# OCR pipeline — optimised for speed
# ----------------------------------------------------------------------
OCR_CONFIG = "--oem 1 --psm 6"
MAX_OCR_WIDTH = 1500  # downscale before OCR; keeps keyword detection accurate, much faster

def process_page(paper, page_num, image_bytes, edition_choice, selected_date):
    """Downloads already done. Runs fast OCR, and only does the heavier
    word-position pass if there's a match. Returns a result dict."""
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
        "paper": paper,
        "edition": edition_choice,
        "date": selected_date,
        "page": page_num,
        "matched": matched,
        "tender_hits": sorted(set(tender_hits)),
        "service_hits": sorted(set(service_hits)),
        "full_img": img,
        "crop_img": crop_img,
        "thumb": thumb,
    }

def crop_around_keywords(img: Image.Image, data: dict, keywords: list, scale: float, padding: int = 80):
    xs1, ys1, xs2, ys2 = [], [], [], []
    n = len(data.get("text", []))
    for i in range(n):
        word = (data["text"][i] or "").strip().upper()
        if not word:
            continue
        if any(k in word or word in k for k in keywords if len(k) <= 20):
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            xs1.append(x); ys1.append(y); xs2.append(x + w); ys2.append(y + h)
    if not xs1:
        return img
    inv = 1 / scale
    left = max(int(min(xs1) * inv) - padding, 0)
    top = max(int(min(ys1) * inv) - padding * 3, 0)
    right = min(int(max(xs2) * inv) + padding, img.width)
    bottom = min(int(max(ys2) * inv) + padding * 3, img.height)
    if right - left < 100 or bottom - top < 100:
        return img
    return img.crop((left, top, right, bottom))

def run_search(selected_papers, selected_date, edition_choice, progress_cb):
    """Fetches + OCRs all selected papers' pages in parallel, returns a flat
    list of result dicts (sorted by paper, page)."""
    jobs = []  # (paper, page_num, bytes)
    for paper in selected_papers:
        info = PAPERS[paper]
        if not info["ready"]:
            continue
        code = info["editions"].get(edition_choice)
        if code is None:
            continue
        pages = info["fetch"](selected_date, code)
        for page_num, content in pages:
            jobs.append((paper, page_num, content))

    results = [None] * len(jobs)
    if not jobs:
        return []

    with ThreadPoolExecutor(max_workers=4) as pool:
        future_map = {
            pool.submit(process_page, paper, page_num, content, edition_choice, selected_date): i
            for i, (paper, page_num, content) in enumerate(jobs)
        }
        done_count = 0
        for future in as_completed(future_map):
            i = future_map[future]
            try:
                results[i] = future.result()
            except Exception:
                results[i] = None
            done_count += 1
            progress_cb(done_count / len(jobs))

    results = [r for r in results if r is not None]
    results.sort(key=lambda r: (r["paper"], r["page"]))
    return results

# ----------------------------------------------------------------------
# Native "share to WhatsApp" widget (uses the phone's own share sheet)
# ----------------------------------------------------------------------
def share_button(img: Image.Image, key: str):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    b64 = base64.b64encode(buf.getvalue()).decode()
    html = f"""
    <div style="text-align:center;">
      <button id="share_{key}" style="
        padding:10px 18px;background:#25D366;color:white;border:none;
        border-radius:8px;font-size:15px;cursor:pointer;width:100%;">
        📲 Share to WhatsApp
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
            document.getElementById("msg_{key}").innerText =
              "Sharing isn't supported in this browser — use the Save button below instead.";
          }}
        }} catch (e) {{ /* user cancelled share sheet, ignore */ }}
      }}
      document.getElementById("share_{key}").addEventListener("click", doShare);
    }})();
    </script>
    """
    components.html(html, height=70)

# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------
st.set_page_config(page_title="Odisha Tender Finder", page_icon="📰", layout="centered")
st.title("📰 Odisha Tender Finder")
st.caption("Scans today's e-papers for English tender/corrigendum notices about security, housekeeping, manpower, or watchman agencies.")

if "results" not in st.session_state:
    st.session_state.results = None
if "dismissed" not in st.session_state:
    st.session_state.dismissed = set()

selected_date = st.date_input("Edition date", value=date.today())
selected_papers = st.multiselect(
    "Newspapers", options=list(PAPERS.keys()), default=["Samaja", "Sambad", "Dharitri"]
)
edition_choice = st.selectbox("Edition (city)", options=ALL_CITIES, index=0)

not_ready = [p for p in selected_papers if not PAPERS[p]["ready"]]
if not_ready:
    st.warning(f"{', '.join(not_ready)} isn't connected yet.")
skipped_for_city = [
    p for p in selected_papers
    if PAPERS[p]["ready"] and edition_choice not in PAPERS[p]["editions"]
]
if skipped_for_city:
    st.caption(f"({', '.join(skipped_for_city)} doesn't publish a '{edition_choice}' edition — will be skipped.)")

go = st.button("🔍 Search for Tenders", type="primary", use_container_width=True)

if go:
    st.session_state.dismissed = set()
    progress = st.progress(0.0, text="Reading pages…")
    st.session_state.results = run_search(
        selected_papers, selected_date, edition_choice,
        progress_cb=lambda frac: progress.progress(frac, text=f"Reading pages… {int(frac*100)}%"),
    )
    progress.empty()

results = st.session_state.results

if results is None:
    st.write("Pick a date and press the button above to start.")
elif len(results) == 0:
    st.info("Couldn't check any pages — either the papers you picked aren't connected yet, or today's edition isn't up yet.")
else:
    matched = [r for r in results if r["matched"]]
    visible_matches = [
        r for r in matched
        if (r["paper"], r["page"]) not in st.session_state.dismissed
    ]

    if not visible_matches:
        st.success("👋 No tenders today. Bye!")
    else:
        st.subheader(f"Found {len(visible_matches)} page(s) worth a look")
        for r in visible_matches:
            key = f"{r['paper']}_{r['page']}"
            with st.container(border=True):
                st.markdown(
                    f"**{r['paper']} — page {r['page']}** &nbsp; "
                    f"matched: `{', '.join(r['tender_hits'])}` + `{', '.join(r['service_hits'])}`"
                )
                st.image(r["crop_img"], use_container_width=True)
                with st.expander("View full page"):
                    st.image(r["full_img"], use_container_width=True)

                c1, c2 = st.columns(2)
                with c1:
                    share_button(r["crop_img"], key)
                with c2:
                    if st.button("❌ Not relevant", key=f"reject_{key}", use_container_width=True):
                        st.session_state.dismissed.add((r["paper"], r["page"]))
                        st.rerun()

                buf = io.BytesIO()
                r["crop_img"].save(buf, format="JPEG", quality=92)
                st.download_button(
                    "⬇️ Or save the image manually",
                    data=buf.getvalue(),
                    file_name=f"{r['paper']}_{r['page']}_{selected_date}.jpg",
                    mime="image/jpeg",
                    key=f"dl_{key}",
                    use_container_width=True,
                )

    # ---- Safety-net thumbnail strip: every page, at a glance ----
    with st.expander(f"🔎 Quick visual check — all {len(results)} pages scanned (skim in ~15 sec)"):
        st.caption("Pages with a red border matched the tender search. Give the rest a quick glance too, in case OCR missed something.")
        cols = st.columns(4)
        for i, r in enumerate(results):
            with cols[i % 4]:
                border = "3px solid #ff4b4b" if r["matched"] else "1px solid #ddd"
                st.markdown(
                    f'<div style="border:{border};border-radius:6px;padding:2px;margin-bottom:8px;">',
                    unsafe_allow_html=True,
                )
                st.image(r["thumb"], caption=f"{r['paper']} p{r['page']}", use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)

st.divider()
st.caption(
    "Tip: this tool narrows ~20+ pages down to a handful worth reading closely — "
    "it saves time, it doesn't replace your judgment. OCR occasionally misses small "
    "or faint print, which is why the quick visual check above exists as a backup."
)
