import os
import json
import asyncio
from typing import Optional, List, Dict
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv, set_key
from fastapi import FastAPI, Depends, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from .core.logging_config import setup_logging, get_logger
from .core.config import get_project_dir, REVERIE_ROOT
from .db.session import init_db, get_db, get_registry_session
from .db.models import Project
from .db.ladybug_db import LadybugClient
from .graph.workflow import app_graph
from .schemas.agent_schemas import ReviewRequest

# Setup Logging
setup_logging()
logger = get_logger(__name__)

app = FastAPI(title="Reverie AI Backend")

# Configure CORS for Vue Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    init_db()

# --- PROJECT ENDPOINTS ---

@app.get("/api/projects")
def list_projects(db: Session = Depends(get_db)):
    """List all projects in the registry."""
    projects = db.query(Project).all()
    return projects

@app.get("/api/projects/{tag}")
def get_project(tag: str, db: Session = Depends(get_db)):
    """Get specific project details."""
    project = db.query(Project).filter(Project.tag == tag).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@app.get("/api/projects/{tag}/summary")
def get_project_summary(tag: str):
    """Fetch the AI-generated summary from the Knowledge Graph."""
    project_dir = get_project_dir(tag)
    client = LadybugClient(db_path=project_dir / "graph_db")
    try:
        res = client.execute("MATCH (p:Project {id: $id}) RETURN p.summary", {"id": tag})
        if res.has_next():
            df = res.get_as_df()
            summary = df.iloc[0]["p.summary"] if not df.empty else None
            return {"summary": summary}
        return {"summary": None}
    finally:
        pass

# --- INGESTION ENDPOINTS ---

@app.post("/api/projects/{tag}/ingest")
async def ingest_project(tag: str, force: bool = False, db: Session = Depends(get_db)):
    """Trigger the ingestion pipeline for a project."""
    project = db.query(Project).filter(Project.tag == tag).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from .agents.ingestion import IngestionPipeline
    pipeline = IngestionPipeline(tag=tag, skip_dirs=project.skip_dirs)
    
    async def run_ingestion():
        await pipeline.process_codebase(project.root_path, force=force)
        
    asyncio.create_task(run_ingestion())
    return {"message": "Ingestion started in background"}

# --- REVIEW ENDPOINTS ---

@app.post("/api/projects/{tag}/review")
async def run_project_review(tag: str, mode: str = "full", prompt: Optional[str] = None, db: Session = Depends(get_db)):
    """Trigger a review for a specific project folder."""
    project = db.query(Project).filter(Project.tag == tag).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_path = project.root_path
    files_to_review = []
    SOURCE_EXTS = (".py", ".js", ".ts", ".tsx", ".go", ".rs", ".c", ".cpp", ".h", ".hpp")

    for root, dirs, files in os.walk(project_path):
        if any(skip in root for skip in [".git", "node_modules", "__pycache__", "venv"]):
            continue
        for file in files:
            if file.endswith(SOURCE_EXTS):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    files_to_review.append({
                        "path": file_path,
                        "content": content,
                        "language": file.split(".")[-1].lower()
                    })
                except: pass

    agent_map = {"bug_detect": "bug_detector", "security": "security", "smell": "smell_detector"}
    selected_modes = [m.strip() for m in mode.split(",")]
    review_mode = "full"
    target_agents = []
    if "full" not in selected_modes:
        review_mode = "subset"
        for m in selected_modes:
            if m in agent_map: target_agents.append(agent_map[m])

    initial_state = {
        "project_tag": tag,
        "project_root": str(project_path),
        "user_prompt": prompt,
        "project_config": {
            "min_severity": project.min_severity,
            "auto_gen_tests": project.auto_gen_tests,
            "max_iterations": project.max_iterations,
            "max_recursion_depth": project.max_recursion_depth,
        },
        "review_mode": review_mode,
        "target_agents": target_agents,
        "files_to_review": files_to_review,
        "bug_findings": [], "security_findings": [], "smell_findings": [],
        "generated_tests": [], "messages": [],
    }

    result = await app_graph.ainvoke(initial_state, {"recursion_limit": 50})
    return {"final_report": result.get("final_report")}

# --- REPORT ENDPOINTS ---

@app.get("/api/projects/{tag}/reports")
def list_reports(tag: str):
    """List historical reports for a project."""
    reports_dir = get_project_dir(tag) / "reports"
    if not reports_dir.exists():
        return []
    
    reports = []
    for f in sorted(reports_dir.glob("report_*.md"), reverse=True):
        reports.append({
            "id": f.name.replace("report_", "").replace(".md", ""),
            "name": f.name,
            "timestamp": datetime.fromtimestamp(f.stat().st_mtime).isoformat()
        })
    return reports

@app.get("/api/projects/{tag}/reports/{report_id}")
def get_report_content(tag: str, report_id: str):
    """Read a specific report's markdown content."""
    report_path = get_project_dir(tag) / "reports" / f"report_{report_id}.md"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    
    with open(report_path, "r", encoding="utf-8") as f:
        return {"content": f.read()}

@app.get("/api/projects/{tag}/reports/{report_id}/sarif")
def get_report_sarif(tag: str, report_id: str):
    """Read a specific report's SARIF JSON content."""
    sarif_path = get_project_dir(tag) / "reports" / f"results_{report_id}.sarif"
    if not sarif_path.exists():
        raise HTTPException(status_code=404, detail="SARIF file not found")
    
    with open(sarif_path, "r", encoding="utf-8") as f:
        return json.load(f)

# --- SETTINGS ENDPOINTS ---

@app.get("/api/settings")
def get_settings():
    """Read current environment settings from ~/.reverie/.env"""
    settings = {
        "LLM_PROVIDER": os.getenv("LLM_PROVIDER", "gemini"),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "OPENAI_MODEL_NAME": os.getenv("OPENAI_MODEL_NAME", "gpt-4o"),
        "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", ""),
        "GEMINI_MODEL_TYPE": os.getenv("GEMINI_MODEL_TYPE", "gemini-1.5-flash"),
        "TAVILY_API_KEY": os.getenv("TAVILY_API_KEY", "")
    }
    return settings

@app.post("/api/settings")
def update_settings(settings: Dict = Body(...)):
    """Save settings to ~/.reverie/.env"""
    global_config_dir = Path.home() / ".reverie"
    global_config_dir.mkdir(parents=True, exist_ok=True)
    env_path = global_config_dir / ".env"
    
    for key, value in settings.items():
        if value is not None:
            set_key(str(env_path), key, str(value))
            os.environ[key] = str(value)
            
    return {"message": "Settings updated successfully"}

# --- FRONTEND STATIC FILES ---

static_path = Path(__file__).parent / "static"

if static_path.exists():
    # 1. Handle Vite's /assets folder specifically for correct MIME types
    assets_path = static_path / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")
    
    # 2. General static folder mount
    app.mount("/static", StaticFiles(directory=static_path), name="static")

@app.get("/", response_class=HTMLResponse)
def read_root():
    index_file = static_path / "index.html"
    if index_file.exists():
        with open(index_file, "r") as f:
            return f.read()
    return "<h1>Reverie AI</h1><p>Frontend not found. Run 'npm build' and copy to app/static.</p>"

@app.get("/{rest_of_path:path}", response_class=HTMLResponse)
def catch_all(rest_of_path: str):
    """Serve index.html for SPA routes, but NOT for missing assets."""
    if rest_of_path.startswith("api/"):
         raise HTTPException(status_code=404, detail="API route not found")
    
    # If the path looks like a file (has an extension), don't serve index.html
    # This prevents the "MIME type mismatch" error for missing JS/CSS files
    if "." in rest_of_path.split("/")[-1]:
        raise HTTPException(status_code=404, detail="File not found")
         
    index_file = static_path / "index.html"
    if index_file.exists():
        with open(index_file, "r") as f:
            return f.read()
    return HTMLResponse(content="Not Found", status_code=404)
