"""
Scraper for https://ihararejobs.com/
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from .utils import DEFAULT_MAX_AGE_DAYS, is_recent

BASE_URL = "https://ihararejobs.com"
LISTING_URL = f"{BASE_URL}/jobs/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_deadline(text: str | None) -> Optional[date]:
    if not text:
        return None
    text = re.sub(r"(?i)expires\s*", "", text).strip()
    try:
        return date_parser.parse(text, fuzzy=True).date()
    except Exception:
        return None


def parse_created_date(text: str | None) -> Optional[date]:
    """'Created 19 Oct 2026' → date."""
    if not text:
        return None
    text = re.sub(r"(?i)created\s*", "", text).strip()
    try:
        return date_parser.parse(text, fuzzy=True).date()
    except Exception:
        return None


def scrape_page(
    page: int = 1, max_age_days: int = DEFAULT_MAX_AGE_DAYS
) -> list[dict]:
    # iHarare typically uses ?page=N or /page/N/ — try both styles
    if page == 1:
        url = LISTING_URL
    else:
        url = f"{LISTING_URL}?page={page}"

    jobs = []

    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

    # Each job block is a .company-list-details div
    details_list = soup.select(".company-list-details")

    for el in details_list:
        title_el = el.select_one("h3 a")
        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        href = title_el.get("href")
        if href and not href.startswith("http"):
            href = urljoin(BASE_URL, href)

        # Location
        loc_el = el.select_one(".company-state")
        location = None
        if loc_el:
            location = re.sub(r".*?map-marker\s*", "", loc_el.get_text(" ", strip=True), flags=re.I).strip()
            location = location or loc_el.get_text(strip=True)

        # Expiry + job type (both use .open-icon)
        deadline_text = None
        job_type = None
        for icon in el.select(".open-icon"):
            txt = icon.get_text(" ", strip=True)
            if re.search(r"(?i)expires", txt):
                deadline_text = txt
            elif re.search(r"(?i)full\s*time|part\s*time|contract|internship|volunteer", txt):
                job_type = re.sub(r".*?clock-o\s*", "", txt, flags=re.I).strip()
                job_type = job_type or txt

        # Company – usually the last meaningful <p>
        company = None
        for p in el.select("p"):
            txt = p.get_text(strip=True)
            if not txt:
                continue
            if re.search(r"(?i)expires|full\s*time|to be shared|created|salary|map-marker", txt):
                continue
            if 2 < len(txt) < 90:
                company = txt  # keep overwriting → last good one is usually company

        # Created date (posted date)
        created_text = None
        created_match = re.search(
            r"Created\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})",
            el.get_text(),
            re.I,
        )
        if created_match:
            created_text = created_match.group(0)

        source_id = href.rstrip("/").split("/")[-1] if href else None

        jobs.append(
            {
                "source": "ihararejobs.com",
                "source_id": source_id,
                "title": title,
                "company": company,
                "location": location,
                "job_type": job_type,
                "category": None,
                "deadline": parse_deadline(deadline_text),
                "relative_posted": None,
                "posted_date": parse_created_date(created_text),
                "url": href,
            }
        )

    return [job for job in jobs if is_recent(job["posted_date"], max_age_days)]


def scrape_all(
    max_pages: int = 5, max_age_days: int = DEFAULT_MAX_AGE_DAYS
) -> list[dict]:
    all_jobs = []
    for page in range(1, max_pages + 1):
        try:
            page_jobs = scrape_page(page, max_age_days=max_age_days)
            if not page_jobs:
                break
            all_jobs.extend(page_jobs)
            print(f"[iHarare] Page {page}: {len(page_jobs)} jobs")
        except Exception as e:
            print(f"[iHarare] Error on page {page}: {e}")
            break
    return all_jobs


if __name__ == "__main__":
    results = scrape_all(max_pages=2)
    for j in results[:3]:
        print(j)
    print(f"\nTotal: {len(results)}")
