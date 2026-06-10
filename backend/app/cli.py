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

@app.command()
def init(
    project_folder: Path = typer.Argument(..., help="Path to the project folder"),
    tag: Optional[str] = typer.Option(None, "--tag", help="Optional project ID/tag")
):
    """Initialize a project with a .reverie.yaml config file."""
    if not project_folder.exists():
        typer.echo(f"Error: Folder {project_folder} does not exist.")
        raise typer.Exit(1)

    project_id = tag or str(uuid.uuid4())[:8]
    config_path = project_folder / ".reverie.yaml"
    
    config_data = {
        "project_id": project_id,
        "path": str(project_folder.absolute()),
        "name": project_folder.name
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
            root_path=str(project_folder.absolute())
        )
        db.add(new_project)
        db.commit()
        logger.info(f"Project '{project_folder.name}' registered globally with tag: {project_id}")
    else:
        logger.info(f"Project with tag {project_id} already registered.")
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
    
    from .agents.ingestion import IngestionPipeline
    pipeline = IngestionPipeline(tag=tag)
    asyncio.run(pipeline.process_codebase(project_path))
    
    typer.echo("Ingestion complete.")
    db.close()

if __name__ == "__main__":
    app()
