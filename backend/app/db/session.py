from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base
from ..core.config import get_project_dir, GLOBAL_DB_PATH

def get_registry_session():
    GLOBAL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{GLOBAL_DB_PATH}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()

def get_engine(tag: str):
    project_dir = get_project_dir(tag)
    db_path = project_dir / "metadata.db"
    url = f"sqlite:///{db_path}"
    return create_engine(url, connect_args={"check_same_thread": False})

def init_project_db(tag: str):
    engine = get_engine(tag)
    Base.metadata.create_all(bind=engine)

def get_db_session(tag: str):
    engine = get_engine(tag)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
