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
# SAMAJA: Direct image URLs, predictable by date.
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
# SAMBAD: Direct image URLs, predictable by date.
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
