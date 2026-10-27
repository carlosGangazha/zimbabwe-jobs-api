import os
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, Query, BackgroundTasks, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session
from .database import engine, get_db, Base
from .models import Job
from .schemas import JobOut, JobsResponse
from .scrapers.iharare import scrape_all as scrape_iharare
from .scrapers.jobszimbabwe import scrape_all as scrape_jobszimbabwe
from .scrapers.vacancymail import scrape_all as scrape_vacancymail
from .scrapers.zimjobsite import scrape_all as scrape_zimjobsite
from .scrapers.utils import DEFAULT_MAX_AGE_DAYS
from fastapi.security import APIKeyHeader

load_dotenv()

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="ZimJobs API",
    description="Aggregates job vacancies from major Zimbabwe job boards.",
    version="0.0.1",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HARARE_TZ = ZoneInfo("Africa/Harare")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

SCRAPE_API_KEY = os.getenv("SCRAPE_API_KEY")

def require_api_key(x_api_key: Optional[str] = Depends(api_key_header)):
    if SCRAPE_API_KEY and x_api_key != SCRAPE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def clean(value):
    """Postgres rejects NUL characters in text."""
    return value.replace("\x00", "") if isinstance(value, str) else value


def upsert_jobs(db: Session, jobs_data: list[dict]):
    """Insert or update jobs by source_id."""
    if not jobs_data:
        return

    # De-duplicate within the batch (last one wins)
    unique = {d["source_id"]: {k: clean(v) for k, v in d.items()} for d in jobs_data}

    existing_jobs = {
        j.source_id: j
        for j in db.execute(
            select(Job).where(Job.source_id.in_(list(unique.keys())))
        ).scalars()
    }

    now = datetime.utcnow()
    for source_id, data in unique.items():
        job = existing_jobs.get(source_id)
        if job:
            for key, value in data.items():
                setattr(job, key, value)
            job.scraped_at = now
        else:
            db.add(Job(**data))

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def paginate(db: Session, query, limit: int, offset: int):
    """Return (total matching rows, current page of rows)."""
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    page = (
        db.execute(query.order_by(Job.scraped_at.desc()).offset(offset).limit(limit))
        .scalars()
        .all()
    )
    return total, page


@app.post("/scrape", tags=["Admin"], dependencies=[Depends(require_api_key)])
def trigger_scrape(
    background_tasks: BackgroundTasks,
    sources: str = Query(
        "all",
        description="Comma-separated or single: all | jobszimbabwe | vacancymail | iharare | zimjobsite",
    ),
    max_pages: int = Query(5, ge=1, le=15),
    max_age_days: int = Query(DEFAULT_MAX_AGE_DAYS, ge=7, le=14),
):
    requested = {s.strip().lower() for s in sources.split(",")}

    def run():
        from .database import SessionLocal

        session = SessionLocal()
        try:
            all_jobs = []

            if "all" in requested or "jobszimbabwe" in requested:
                print("→ Scraping jobszimbabwe.co.zw ...")
                all_jobs.extend(
                    scrape_jobszimbabwe(max_pages=max_pages, max_age_days=max_age_days)
                )

            if "all" in requested or "vacancymail" in requested:
                print("→ Scraping vacancymail.co.zw ...")
                all_jobs.extend(
                    scrape_vacancymail(max_pages=max_pages, max_age_days=max_age_days)
                )

            if "all" in requested or "iharare" in requested:
                print("→ Scraping ihararejobs.com ...")
                all_jobs.extend(
                    scrape_iharare(max_pages=max_pages, max_age_days=max_age_days)
                )

            if "all" in requested or "zimjobsite" in requested:
                print("→ Scraping zimjobsite.com ...")
                all_jobs.extend(
                    scrape_zimjobsite(max_pages=max_pages, max_age_days=max_age_days)
                )

            upsert_jobs(session, all_jobs)
            print(f"✓ Upserted {len(all_jobs)} jobs total")
        except Exception as e:
            print(f"✗ Scrape failed: {e}")
        finally:
            session.close()

    background_tasks.add_task(run)
    return {
        "message": "Scrape started",
        "sources": list(requested),
        "max_pages": max_pages,
        "max_age_days": max_age_days,
    }


def require_admin_key(x_api_key: Optional[str] = Depends(api_key_header)):
    """Stricter than require_api_key: always needs a key, even if none is configured."""
    if not SCRAPE_API_KEY or x_api_key != SCRAPE_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@app.delete("/jobs", tags=["Admin"], dependencies=[Depends(require_admin_key)])
def delete_all_jobs(
    confirm: bool = Query(False, description="Must be true to delete everything"),
    db: Session = Depends(get_db),
):
    """Delete ALL jobs from the database."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Add ?confirm=true to delete all jobs",
        )

    try:
        result = db.execute(delete(Job))
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {"message": "All jobs deleted", "deleted": result.rowcount}


@app.get("/jobs", response_model=JobsResponse, tags=["Jobs"])
def get_jobs(
    date: Optional[date] = Query(
        None,
        description="Filter by posted_date (YYYY-MM-DD). Leave empty for all.",
    ),
    location: Optional[str] = Query(None, description="Filter by location (partial match)"),
    keyword: Optional[str] = Query(None, description="Search in title or company"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Get job vacancies.
    Use `date` to get jobs posted on a specific day.
    """
    query = select(Job)

    if date:
        query = query.where(Job.posted_date == date)
    if location and location.strip():
        query = query.where(Job.location.ilike(f"%{location.strip()}%"))
    if keyword and keyword.strip():
        query = query.where(
            (Job.title.ilike(f"%{keyword.strip()}%"))
            | (Job.company.ilike(f"%{keyword.strip()}%"))
        )

    total, results = paginate(db, query, limit, offset)

    return JobsResponse(date=date, total=total, jobs=results)


# find all jobs posted today in zimbabwe
@app.get("/jobs/today", response_model=JobsResponse, tags=["Jobs"])
def get_jobs_today(
    location: Optional[str] = Query(
        None,
        description="Optional location filter (partial match). Leave empty for all of Zimbabwe.",
    ),
    keyword: Optional[str] = Query(
        None,
        description="Optional search in title or company",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Return all jobs posted / created on the current day (Africa/Harare timezone).
    Leave location empty to get every job in Zimbabwe for today.
    """
    today = datetime.now(HARARE_TZ).date()

    query = select(Job).where(Job.posted_date == today)

    # Treat empty strings from Swagger as "not provided"
    if location and location.strip():
        query = query.where(Job.location.ilike(f"%{location.strip()}%"))

    if keyword and keyword.strip():
        query = query.where(
            (Job.title.ilike(f"%{keyword.strip()}%"))
            | (Job.company.ilike(f"%{keyword.strip()}%"))
        )

    total, results = paginate(db, query, limit, offset)

    return JobsResponse(date=today, total=total, jobs=results)


# search by title to see if you meet any criteria
@app.get("/jobs/today/search", response_model=JobsResponse, tags=["Jobs"])
def search_todays_jobs_by_title(
    title: str = Query(..., min_length=1, description="Search term for job title (required)"),
    location: Optional[str] = Query(None, description="Optional location filter"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Search today's job vacancies by title.
    Example: /jobs/today/search?title=accountant
    """
    today = datetime.now(HARARE_TZ).date()

    query = (
        select(Job)
        .where(Job.posted_date == today)
        .where(Job.title.ilike(f"%{title.strip()}%"))
    )

    if location and location.strip():
        query = query.where(Job.location.ilike(f"%{location.strip()}%"))

    total, results = paginate(db, query, limit, offset)

    return JobsResponse(date=today, total=total, jobs=results)


# end point to get a vacancy detail in ui
@app.get("/jobs/{job_id}", response_model=JobOut, tags=["Jobs"])
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}