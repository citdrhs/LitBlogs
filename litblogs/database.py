# database.py
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from base import Base

BASE_DIR = Path(__file__).resolve().parent
BASE_ENV_PATH = BASE_DIR / ".env"

base_environment = dotenv_values(BASE_ENV_PATH)
app_env = (os.getenv("APP_ENV") or base_environment.get("APP_ENV") or "development").strip().lower()
env_override_path = BASE_DIR / f".env.{app_env}"
if env_override_path.exists():
    load_dotenv(env_override_path, override=False)
load_dotenv(BASE_ENV_PATH, override=False)

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def initialize_database():
    Base.metadata.create_all(bind=engine)

def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
