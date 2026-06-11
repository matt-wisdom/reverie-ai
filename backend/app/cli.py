import typer
import yaml
import os
import uuid
import asyncio
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from .db.session import get_registry_session, init_project_db
from .db.models import Project
from .core.logging_config import setup_logging, get_logger

setup_logging()
logger = get_logger("reverie-cli")

app = typer.Typer(help="Reverie Code Ingestion CLI")
context_app = typer.Typer(help="Manage project context documents")
app.add_typer(context_app, name="context")

DEFAULT_SKIP_DIRS = [
    ".git", "node_modules", "__pycache__", "venv", ".venv", 
    "dist", "build", ".reverie.yaml", ".pytest_cache", 
    "chroma_data", "chroma_db", "dataset", ".idea", ".vscode"
]

@app.command()
def init(
    project_folder: Path = typer.Argument(..., help="Path to the project folder"),
    tag: Optional[str] = typer.Option(None, "--tag", help="Optional project ID/tag"),
    min_severity: str = typer.Option("medium", help="Minimum severity threshold (low, medium, high, critical)"),
    auto_gen_tests: bool = typer.Option(True, help="Automatically generate tests"),
    min_coverage: int = typer.Option(80, help="Minimum test coverage percentage")
):
    """Initialize a project with a .reverie.yaml config file."""
    if not project_folder.exists():
        typer.echo(f"Error: Folder {project_folder} does not exist.")
        raise typer.Exit(1)

    project_id = tag or str(uuid.uuid4())[:8]
    config_path = project_folder / ".reverie.yaml"
    
    config_data = {
        "project_id": project_id,
        "name": project_folder.name,
        "path": str(project_folder.absolute()),
        "configs": {
            "min_severity": min_severity,
            "skip_dirs": DEFAULT_SKIP_DIRS,
            "auto_gen_tests": auto_gen_tests,
            "min_coverage": min_coverage,
            "custom_rules": []
        }
    }

    with open(config_path, "w") as f:
        yaml.dump(config_data, f)

    # Register in Global Registry
    db = get_registry_session()
    existing = db.query(Project).filter(Project.tag == project_id).first()
    if not existing:
        new_project = Project(
            tag=project_id,
            name=project_folder.name,
            root_path=str(project_folder.absolute()),
            min_severity=min_severity,
            skip_dirs=DEFAULT_SKIP_DIRS,
            auto_gen_tests=auto_gen_tests,
            min_coverage=min_coverage,
            custom_rules=[]
        )
        db.add(new_project)
        db.commit()
        logger.info(f"Project '{project_folder.name}' registered globally with tag: {project_id}")
    else:
        logger.info(f"Project with tag {project_id} already registered. Updating configs...")
        existing.min_severity = min_severity
        existing.auto_gen_tests = auto_gen_tests
        existing.min_coverage = min_coverage
        db.commit()
    db.close()
    
    # Initialize project-specific metadata DB
    init_project_db(project_id)

    typer.echo(f"Initialized Reverie config in {config_path}")
    typer.echo(f"Project Tag: {project_id}")

@app.command()
def load(tag: str):
    """Begin ingestion of the project folder associated with the tag."""
    db = get_registry_session()
    project = db.query(Project).filter(Project.tag == tag).first()
    
    if not project:
        # Fallback: check if .reverie.yaml exists in current dir
        config_path = Path(".reverie.yaml")
        if config_path.exists():
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
                if config.get("project_id") == tag:
                    project_path = config.get("path")
                else:
                    typer.echo(f"Error: Project with tag {tag} not found.")
                    raise typer.Exit(1)
        else:
            typer.echo(f"Error: Project with tag {tag} not found.")
            raise typer.Exit(1)
    else:
        project_path = project.root_path

    if not os.path.exists(project_path):
        typer.echo(f"Error: Project path {project_path} no longer exists.")
        raise typer.Exit(1)

    typer.echo(f"Loading project: {tag} from {project_path}")
    
    skip_dirs = project.skip_dirs if project else []
    
    from .agents.ingestion import IngestionPipeline
    pipeline = IngestionPipeline(tag=tag, skip_dirs=skip_dirs)
    asyncio.run(pipeline.process_codebase(project_path))
    
    typer.echo("Ingestion complete.")
    db.close()

@context_app.command("add")
def context_add(
    tag: str = typer.Argument(..., help="Project tag"),
    source: str = typer.Argument(..., help="File path or URL to the document"),
    doc_type: str = typer.Option("reference", help="Type of document (style_guide, adr, reference, runbook)")
):
    """Add a document (PDF, MD, TXT) to the project context."""
    db = get_registry_session()
    project = db.query(Project).filter(Project.tag == tag).first()
    if not project:
        typer.echo(f"Error: Project with tag {tag} not found.")
        raise typer.Exit(1)
    
    project_dir = get_project_dir(tag)
    from .agents.context_processor import ContextProcessor
    processor = ContextProcessor(tag=tag, project_dir=project_dir)
    
    try:
        doc_id = asyncio.run(processor.add_context(source, doc_type))
        typer.echo(f"Successfully added context document. ID: {doc_id}")
    except Exception as e:
        typer.echo(f"Error adding context: {e}")
        raise typer.Exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    app()
