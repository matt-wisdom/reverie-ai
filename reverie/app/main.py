import os
from dotenv import load_dotenv
from .core.logging_config import setup_logging, get_logger

# Load environment variables from .env file
load_dotenv()
setup_logging()
logger = get_logger(__name__)

from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from .db.session import init_db, get_db
from .db.ladybug_db import ladybug_client
from .graph.workflow import app_graph
from .schemas.agent_schemas import ReviewRequest

app = FastAPI(title="CodeRabbit-like Backend")


@app.on_event("startup")
def on_startup():
    init_db()
    ladybug_client.init_schema()


@app.get("/")
def read_root():
    return {"message": "CodeRabbit-like Backend is running"}


@app.post("/review")
async def run_review(request: ReviewRequest):
    # Initialize state
    initial_state = {
        "project_tag": request.project_name or "default",
        "messages": [],
        "code": request.code,
        "review_results": [],
        "vulnerability_results": [],
        "test_results": [],
        "final_report": "",
        "current_task": "start",
    }

    # Run the graph
    result = await app_graph.ainvoke(initial_state)
    return result
