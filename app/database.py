import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./jobs.db").strip()

# Tolerate common paste mistakes: wrapping quotes, or "DATABASE_URL=" inside the value
DATABASE_URL = DATABASE_URL.strip('"').strip("'").strip()
if DATABASE_URL.startswith("DATABASE_URL="):
    DATABASE_URL = DATABASE_URL.split("=", 1)[1].strip().strip('"').strip("'")

# Use the psycopg (v3) driver for Postgres
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# Temporary debug line: shows the scheme and host only, never the password
print("DB scheme:", DATABASE_URL.split("://")[0], "| host:", DATABASE_URL.split("@")[-1][:60])

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()