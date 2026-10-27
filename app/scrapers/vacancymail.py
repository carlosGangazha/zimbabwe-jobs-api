"""
Scraper for https://vacancymail.co.zw/
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

BASE_URL = "https://vacancymail.co.zw"
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
    """Convert '6 hours, 35 minutes' / '2 days' etc. into a date."""
    if not text:
        return None
    text = text.lower().replace("\xa0", " ").strip()
    now = datetime.utcnow()

    if any(x in text for x in ["hour", "minute", "just now"]):
        return now.date()
    if "day" in text:
        match = re.search(r"(\d+)\s*day", text)
        if match:
            return (now - timedelta(days=int(match.group(1)))).date()
    if "week" in text:
        match = re.search(r"(\d+)\s*week", text)
        if match:
            return (now - timedelta(weeks=int(match.group(1)))).date()
    return now.date()


def parse_deadline(text: str | None) -> Optional[date]:
    if not text:
        return None
    # Clean "Expires 29 Dec 2026" → "29 Dec 2026"
    text = re.sub(r"(?i)expires\s*", "", text).strip()
    try:
        return date_parser.parse(text, fuzzy=True).date()
    except Exception:
        return None


def extract_company_from_title(title: str) -> tuple[str, Optional[str]]:
    """Handle patterns like 'Title: Company' or 'Title – Company'."""
    for sep in [": ", " – ", " - ", "–"]:
        if sep in title:
            parts = title.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return title, None


def scrape_page(
    page: int = 1, max_age_days: int = DEFAULT_MAX_AGE_DAYS
) -> list[dict]:
    url = LISTING_URL if page == 1 else f"{LISTING_URL}?page={page}"
    jobs = []

    with httpx.Client(headers=HEADERS, timeout=30.0, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

    # Each job is an <a class="job-listing">
    listings = soup.select("a.job-listing")

    for listing in listings:
        title_el = listing.select_one("h3.job-listing-title")
        if not title_el:
            continue

        raw_title = title_el.get_text(strip=True)
        title, company_from_title = extract_company_from_title(raw_title)

        href = listing.get("href")
        if href and not href.startswith("http"):
            href = urljoin(BASE_URL, href)

        # Footer metadata
        footer_items = [li.get_text(" ", strip=True) for li in listing.select(".job-listing-footer li")]

        location = None
        deadline_text = None
        job_type = None
        relative_posted = None

        for item in footer_items:
            item_clean = item.replace("\xa0", " ")
            if re.search(r"(?i)expires", item_clean):
                deadline_text = item_clean
            elif re.search(r"(?i)full\s*time|part\s*time|contract|internship|volunteer", item_clean):
                job_type = item_clean
            elif re.search(r"(?i)posted", item_clean):
                relative_posted = re.sub(r"(?i)posted\s*", "", item_clean).strip()
            elif not location and not re.search(r"(?i)tba|salary|wallet", item_clean):
                # First remaining item is usually location
                location = item_clean

        # Sometimes company is clearer in the description paragraph
        company = company_from_title
        desc_el = listing.select_one(".job-listing-text, p.job-listing-text")
        if desc_el and not company:
            first_line = desc_el.get_text(strip=True).split("\n")[0][:80]
            # Heuristic: uppercase company names often appear first
            if first_line.isupper() or first_line.istitle():
                company = first_line

        source_id = href.rstrip("/").split("/")[-1] if href else None

        jobs.append(
            {
                "source": "vacancymail.co.zw",
                "source_id": source_id,
                "title": title,
                "company": company,
                "location": location,
                "job_type": job_type,
                "category": None,  # VacancyMail listing page doesn't always show category cleanly
                "deadline": parse_deadline(deadline_text),
                "relative_posted": relative_posted,
                "posted_date": parse_relative_date(relative_posted),
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
            print(f"[VacancyMail] Page {page}: {len(page_jobs)} jobs")
        except Exception as e:
            print(f"[VacancyMail] Error on page {page}: {e}")
            break
    return all_jobs


if __name__ == "__main__":
    results = scrape_all(max_pages=2)
    for j in results[:3]:
        print(j)
    print(f"\nTotal: {len(results)}")
