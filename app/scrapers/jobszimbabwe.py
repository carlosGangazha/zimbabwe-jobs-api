"""
Scraper for https://jobszimbabwe.co.zw/
Uses the Noo JobMonster theme structure.
"""

from __future__ import annotations

import re
from datetime import datetime, date, timedelta
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from .utils import DEFAULT_MAX_AGE_DAYS, is_recent

BASE_URL = "https://jobszimbabwe.co.zw"
LISTING_URL = f"{BASE_URL}/jobs/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_relative_date(text: str | None) -> Optional[date]:
    """Convert '2 hours ago', '3 days ago' etc. into a date."""
    if not text:
        return None
    text = text.lower().strip()
    now = datetime.utcnow()

    if "hour" in text or "minute" in text or "just now" in text:
        return now.date()
    if "day" in text:
        match = re.search(r"(\d+)\s*day", text)
        if match:
            days = int(match.group(1))
            return (now - timedelta(days=days)).date()
    if "week" in text:
        match = re.search(r"(\d+)\s*week", text)
        if match:
            weeks = int(match.group(1))
            return (now - timedelta(weeks=weeks)).date()
    return now.date()  # fallback


def parse_deadline(text: str | None) -> Optional[date]:
    if not text:
        return None
    try:
        return date_parser.parse(text, fuzzy=True).date()
    except Exception:
        return None


def extract_company(title: str) -> tuple[str, Optional[str]]:
    """Split 'TITLE – Company' pattern."""
    for sep in [" – ", " –", "– ", " - ", " –"]:
        if sep in title:
            parts = title.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return title, None


def scrape_page(
    page: int = 1, max_age_days: int = DEFAULT_MAX_AGE_DAYS
) -> list[dict]:
    url = LISTING_URL if page == 1 else f"{BASE_URL}/jobs/page/{page}/"
    jobs = []

    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

    articles = soup.select("article.noo_job, article.type-noo_job")

    for art in articles:
        title_el = art.select_one("h3.loop-item-title a")
        if not title_el:
            continue

        raw_title = title_el.get_text(strip=True)
        title, company = extract_company(raw_title)
        url = title_el.get("href")
        if url and not url.startswith("http"):
            url = urljoin(BASE_URL, url)

        # Job type
        type_el = art.select_one(".job-type span, .job-type a span")
        job_type = type_el.get_text(strip=True) if type_el else None

        # Location
        loc_el = art.select_one('[itemprop="jobLocation"], a[href*="jobs-in-"]')
        location = loc_el.get_text(strip=True) if loc_el else None

        # Category
        cat_el = art.select_one('a[href*="job-category"]')
        category = cat_el.get_text(strip=True) if cat_el else None

        # Relative time ("2 hours ago")
        relative = None
        for el in art.find_all(string=re.compile(r"ago|hours?|days?|minutes?", re.I)):
            txt = el.strip()
            if len(txt) < 30:
                relative = txt
                break

        # Deadline (e.g. "November 2, 2026")
        deadline_text = None
        deadline_match = re.search(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
            art.get_text(),
        )
        if deadline_match:
            deadline_text = deadline_match.group(0)

        # Unique source id from URL slug
        source_id = url.rstrip("/").split("/")[-1] if url else None

        jobs.append(
            {
                "source": "jobszimbabwe.co.zw",
                "source_id": source_id,
                "title": title,
                "company": company,
                "location": location,
                "job_type": job_type,
                "category": category,
                "deadline": parse_deadline(deadline_text),
                "relative_posted": relative,
                "posted_date": parse_relative_date(relative),
                "url": url,
            }
        )

    return [job for job in jobs if is_recent(job["posted_date"], max_age_days)]


def scrape_all(
    max_pages: int = 5, max_age_days: int = DEFAULT_MAX_AGE_DAYS
) -> list[dict]:
    """Scrape multiple pages (default first 5 ≈ 75 jobs)."""
    all_jobs = []
    for page in range(1, max_pages + 1):
        try:
            page_jobs = scrape_page(page, max_age_days=max_age_days)
            if not page_jobs:
                break
            all_jobs.extend(page_jobs)
            print(f"Page {page}: {len(page_jobs)} jobs")
        except Exception as e:
            print(f"Error on page {page}: {e}")
            break
    return all_jobs


if __name__ == "__main__":
    # Quick test
    results = scrape_all(max_pages=2)
    for j in results[:3]:
        print(j)
    print(f"\nTotal scraped: {len(results)}")
