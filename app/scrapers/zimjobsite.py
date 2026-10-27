"""
Scraper for https://www.zimjobsite.com/jobs
"""

from __future__ import annotations

import re
from datetime import datetime, date, timedelta
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .utils import DEFAULT_MAX_AGE_DAYS, is_recent

BASE_URL = "https://www.zimjobsite.com"
LISTING_URL = f"{BASE_URL}/jobs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_relative_date(text: str | None) -> Optional[date]:
    """Convert '1 day ago', '4 days ago', '2 hours ago' etc. into a date."""
    if not text:
        return None
    text = text.lower().strip()
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


def extract_company_from_title(title: str) -> tuple[str, Optional[str]]:
    """
    Many titles follow 'JOB TITLE - COMPANY' or 'JOB TITLE – COMPANY'.
    """
    for sep in [" - ", " – ", " –", "– "]:
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

    # Each job is wrapped in .job-items (or the inner .card-grid-2)
    items = soup.select(".job-items")
    if not items:
        items = soup.select(".card-grid-2")

    seen_urls = set()

    for el in items:
        title_el = el.select_one("h4 a, .card-block-info h4 a")
        if not title_el:
            continue

        raw_title = title_el.get_text(strip=True)
        href = title_el.get("href")
        if href and not href.startswith("http"):
            href = urljoin(BASE_URL, href)

        # Avoid duplicates (the page sometimes renders the same card twice in DOM)
        if href in seen_urls:
            continue
        seen_urls.add(href)

        title, company_from_title = extract_company_from_title(raw_title)

        # Company link (often just "Zimjobsite" – the platform). Prefer title-extracted company.
        company_el = el.select_one("a.name-job")
        platform_company = company_el.get_text(strip=True) if company_el else None
        company = company_from_title or (platform_company if platform_company and platform_company.lower() != "zimjobsite" else None)

        # Location
        loc_el = el.select_one(".location-icon, .card-location, .right-info span")
        location = None
        if loc_el:
            location = loc_el.get_text(strip=True)
        if not location:
            # Fallback regex
            m = re.search(r"(Harare|Bulawayo|Mutare|Gweru|Masvingo|Kwekwe|Norton|[\w\s]+),\s*ZW", el.get_text())
            if m:
                location = m.group(0)

        # Job type
        type_el = el.select_one(".card-briefcase")
        job_type = type_el.get_text(strip=True) if type_el else None

        # Relative time
        time_el = el.select_one(".card-time span")
        relative = time_el.get_text(strip=True) if time_el else None

        source_id = href.rstrip("/").split("/")[-1] if href else None

        jobs.append(
            {
                "source": "zimjobsite.com",
                "source_id": source_id,
                "title": title,
                "company": company,
                "location": location,
                "job_type": job_type,
                "category": None,
                "deadline": None,          # listing page does not show deadline cleanly
                "relative_posted": relative,
                "posted_date": parse_relative_date(relative),
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
            print(f"[ZimJobSite] Page {page}: {len(page_jobs)} jobs")
        except Exception as e:
            print(f"[ZimJobSite] Error on page {page}: {e}")
            break
    return all_jobs


if __name__ == "__main__":
    results = scrape_all(max_pages=2)
    for j in results[:3]:
        print(j)
    print(f"\nTotal: {len(results)}")
