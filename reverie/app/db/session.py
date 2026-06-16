from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base
from ..core.config import get_project_dir, GLOBAL_DB_PATH


def get_engine_registry():
    GLOBAL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{GLOBAL_DB_PATH}", connect_args={"check_same_thread": False}
    )


def init_db():
    """Initialize the global registry database."""
    engine = get_engine_registry()
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency for registry database session."""
    engine = get_engine_registry()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_registry_session():
    """Direct session getter for CLI/Scripts."""
    engine = get_engine_registry()
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
