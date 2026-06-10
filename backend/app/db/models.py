from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

DATABASE_URL = "sqlite:///./code_review.db"

Base = declarative_base()

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    tag = Column(String, unique=True, index=True)
    name = Column(String, index=True)
    root_path = Column(String)
    repo_url = Column(String, nullable=True)
    
    # Configs
    min_severity = Column(String, default="medium")
    skip_dirs = Column(JSON, default=list)
    auto_gen_tests = Column(Boolean, default=True)
    min_coverage = Column(Integer, default=80)
    custom_rules = Column(JSON, default=list)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    reports = relationship("Report", back_populates="project")

class Report(Base):
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    project = relationship("Project", back_populates="reports")
