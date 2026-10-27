from datetime import datetime, date
from sqlalchemy import String, Text, Date, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source: Mapped[str] = mapped_column(String(100), index=True)
    source_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500))
    company: Mapped[str | None] = mapped_column(String(300), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    relative_posted: Mapped[str | None] = mapped_column(String(100), nullable=True)
    posted_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    url: Mapped[str] = mapped_column(Text)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)