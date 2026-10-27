from datetime import date, datetime
from pydantic import BaseModel, HttpUrl

class JobOut(BaseModel):
    id: int
    source: str
    title: str
    company: str | None
    location: str | None
    job_type: str | None
    category: str | None
    deadline: date | None
    relative_posted: str | None
    posted_date: date | None
    url: str
    scraped_at: datetime

    class Config:
        from_attributes = True

class JobsResponse(BaseModel):
    date: date | None
    total: int
    jobs: list[JobOut]
