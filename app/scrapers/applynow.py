"""
Scraper for https://applynow.co.zw/ — Zimbabwe roles only.
"""

from __future__ import annotations

import re
from datetime import datetime, date
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from .utils import is_recent

BASE_URL = "https://applynow.co.zw"
ZIMBABWE_URL = f"{BASE_URL}/destination/zimbabwe/"
HOME_URL = f"{BASE_URL}/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

ZIM_KEYWORDS = re.compile(
    r"\b(zimbabwe|harare|bulawayo|mutare|gweru|masvingo|kwekwe|"
    r"chitungwiza|norton|marondera|bindura|gwanda|chiredzi|"
    r"victoria\s*falls|chipinge|masvingo)\b",
    re.I,
)

EXCLUDE_IF_ONLY = re.compile(
    r"\b(remote\s+worldwide|fully\s+remote\s+global|us\$|€|£)\b",
    re.I,
)


def parse_deadline(text: str | None) -> Optional[date]:
    if not text:
        return None
    text = re.sub(r"(?i)closing\s*date\s*:?\s*", "", text).strip()
    try:
        return date_parser.parse(text, fuzzy=True).date()
    except Exception:
        return None


def is_zimbabwe_role(title: str, location: str | None, body: str = "") -> bool:
    """Keep only roles that clearly relate to Zimbabwe."""
    blob = f"{title} {location or ''} {body}"
    if not ZIM_KEYWORDS.search(blob):
        return False
    # Optional: drop pure global remote with no Zim location signal
    if location and re.search(r"(?i)^remote$", location.strip()):
        if not ZIM_KEYWORDS.search(f"{title} {body}"):
            return False
    return True


def extract_from_listing_card(el, base: str = BASE_URL) -> dict | None:
    """Parse a card / article from the destination or archive page."""
    link = el.select_one("a[href*='applynow.co.zw'], h2 a, h3 a, .entry-title a")
    if not link:
        return None

    href = link.get("href") or ""
    if not href.startswith("http"):
        href = urljoin(base, href)

    # Skip pure category / destination pages
    if "/destination/" in href or "/category/" in href:
        return None

    title = link.get_text(strip=True)
    if not title or len(title) < 5:
        return None

    text = el.get_text(" ", strip=True)

    # Location heuristics
    location = None
    loc_match = re.search(
        r"(Harare|Bulawayo|Mutare|Gweru|Masvingo|Kwekwe|Norton|"
        r"Marondera|Bindura|Gwanda|Chiredzi|Victoria\s*Falls|"
        r"Chipinge|Zimbabwe)[^\n,]{0,40}",
        text,
        re.I,
    )
    if loc_match:
        location = loc_match.group(0).strip()

    # Deadline
    deadline_text = None
    dm = re.search(
        r"(?:Closing|Apply by|Deadline)[:\s]*(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4})",
        text,
        re.I,
    )
    if dm:
        deadline_text = dm.group(1)

    company = None
    cm = re.search(
        r"(?:Organisation|Organization|Company)[:\s]+([^\n|]+)",
        text,
        re.I,
    )
    if cm:
        company = cm.group(1).strip()[:120]
    if not company:
        # Fallback: "X is hiring" pattern
        hm = re.search(r"^(.+?)\s+is\s+hiring", title, re.I)
        if hm:
            company = hm.group(1).strip()

    if not is_zimbabwe_role(title, location, text):
        return None

    source_id = href.rstrip("/").split("/")[-1] or href

    posted_date = None
    um = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", href)
    if um:
        try:
            posted_date = date(int(um.group(1)), int(um.group(2)), int(um.group(3)))
        except ValueError:
            pass

    return {
        "source": "applynow.co.zw",
        "source_id": source_id,
        "title": title[:300],
        "company": company,
        "location": location or "Zimbabwe",
        "job_type": None,
        "category": None,
        "deadline": parse_deadline(deadline_text),
        "relative_posted": None,
        "posted_date": posted_date,
        "url": href,
    }


def scrape_page(url: str) -> list[dict]:
    jobs = []
    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text

    if "One moment, please" in html or "cf-browser-verification" in html.lower():
        print("[ApplyNOW] Cloudflare challenge detected — need browser/proxy")
        return []

    soup = BeautifulSoup(html, "lxml")

    cards = soup.select(
        "article, .post, .opportunity, .job-listing, "
        ".entry, .card, .list-item, h2.entry-title, "
        ".wp-block-post, .type-post"
    )
    if not cards:
        # Fallback: any link that looks like a dated post
        cards = soup.select("a[href*='/20']")

    seen = set()
    for el in cards:
        job = extract_from_listing_card(el if el.name != "a" else el.parent or el)
        if not job:
            continue
        if job["url"] in seen:
            continue
        seen.add(job["url"])
        jobs.append(job)

    return jobs


def scrape_all(max_pages: int = 3, max_age_days: int = 14) -> list[dict]:
    """
    Scrape Zimbabwe destination page + a few paginated pages if available.
    Only keeps Zimbabwe roles and recent postings.
    """
    all_jobs = []
    urls = [ZIMBABWE_URL, HOME_URL]

    for page in range(2, max_pages + 1):
        urls.append(f"{BASE_URL}/destination/zimbabwe/page/{page}/")
        urls.append(f"{BASE_URL}/page/{page}/")

    seen_urls = set()
    for url in urls:
        try:
            page_jobs = scrape_page(url)
            for j in page_jobs:
                if j["url"] in seen_urls:
                    continue
                # Recency filter
                if j.get("posted_date") and not is_recent(j["posted_date"], max_age_days):
                    continue
                # If no posted_date, keep only if deadline is still in the future
                if not j.get("posted_date") and j.get("deadline"):
                    if j["deadline"] < date.today():
                        continue
                seen_urls.add(j["url"])
                all_jobs.append(j)
            print(f"[ApplyNOW] {url}: +{len(page_jobs)} candidates")
        except Exception as e:
            print(f"[ApplyNOW] Error on {url}: {e}")

    print(f"[ApplyNOW] Total Zimbabwe roles kept: {len(all_jobs)}")
    return all_jobs


if __name__ == "__main__":
    results = scrape_all(max_pages=2, max_age_days=14)
    for j in results[:5]:
        print(j)
    print(f"\nTotal: {len(results)}")