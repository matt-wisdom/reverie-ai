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
from .core.config import get_project_dir

setup_logging()
logger = get_logger("reverie-cli")

app = typer.Typer(help="Reverie Code Ingestion CLI")
context_app = typer.Typer(help="Manage project context documents")
app.add_typer(context_app, name="context")

DEFAULT_SKIP_DIRS = [
    ".git",
    "node_modules",
    "__pycache__",
    "venv",
    ".venv",
    "dist",
    "build",
    ".reverie.yaml",
    ".pytest_cache",
    "chroma_data",
    "chroma_db",
    "dataset",
    ".idea",
    ".vscode",
]


@app.command()
def init(
    project_folder: Path = typer.Argument(..., help="Path to the project folder"),
    tag: Optional[str] = typer.Option(None, "--tag", help="Optional project ID/tag"),
    min_severity: str = typer.Option(
        "medium", help="Minimum severity threshold (low, medium, high, critical)"
    ),
    auto_gen_tests: bool = typer.Option(True, help="Automatically generate tests"),
    min_coverage: int = typer.Option(80, help="Minimum test coverage percentage"),
    max_iterations: int = typer.Option(25, help="Maximum ReAct loop iterations"),
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
            "max_iterations": max_iterations,
            "custom_rules": [],
        },
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
            max_iterations=max_iterations,
            custom_rules=[],
        )
        db.add(new_project)
        db.commit()
        logger.info(
            f"Project '{project_folder.name}' registered globally with tag: {project_id}"
        )
    else:
        logger.info(
            f"Project with tag {project_id} already registered. Updating configs..."
        )
        existing.min_severity = min_severity
        existing.auto_gen_tests = auto_gen_tests
        existing.min_coverage = min_coverage
        existing.max_iterations = max_iterations
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
    doc_type: str = typer.Option(
        "reference", help="Type of document (style_guide, adr, reference, runbook)"
    ),
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


@app.command()
def review(
    tag: str = typer.Argument(..., help="Project tag"),
    mode: str = typer.Option(
        "full", help="Review mode: full, bug_detect, security, smell, tests"
    ),
):
    """Run the multi-agent review workflow on a project."""
    db = get_registry_session()
    project = db.query(Project).filter(Project.tag == tag).first()
    if not project:
        typer.echo(f"Error: Project with tag {tag} not found.")
        raise typer.Exit(1)

    project_path = project.root_path
    if not os.path.exists(project_path):
        typer.echo(f"Error: Project path {project_path} no longer exists.")
        raise typer.Exit(1)

    # 1. Collect files for review (simplified for full mode)
    files_to_review = []
    for root, dirs, files in os.walk(project_path):
        # Use same skip logic as ingestion
        dirs[:] = [d for d in dirs if d not in DEFAULT_SKIP_DIRS]
        for file in files:
            if file.endswith((".py", ".js", ".ts", ".tsx", ".vue")):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    files_to_review.append(
                        {
                            "path": file_path,
                            "content": content,
                            "language": file.split(".")[-1],
                        }
                    )
                except Exception as e:
                    logger.warning(f"Could not read file {file_path}: {e}")

    # 2. Map mode to target agent if needed
    review_mode = "full"
    target_agent = None
    if mode in ["bug_detect", "security", "smell", "tests"]:
        review_mode = "single"
        # Map CLI options to agent keys used in orchestrator
        agent_map = {
            "bug_detect": "bug_detector",
            "security": "security",
            "smell": "smell_detector",
            "tests": "test_writer",
        }
        target_agent = agent_map[mode]

    # 3. Initialize state
    initial_state = {
        "project_tag": tag,
        "project_root": str(project_path),
        "project_config": {
            "min_severity": project.min_severity if project else "medium",
            "auto_gen_tests": project.auto_gen_tests if project else True,
            "min_coverage": project.min_coverage if project else 80,
            "max_iterations": project.max_iterations if project else 15,
            "max_recursion_depth": project.max_recursion_depth if project else 3,
            "custom_rules": project.custom_rules if project else [],
        },
        "review_mode": review_mode,
        "target_agent": target_agent,
        "files_to_review": files_to_review,
        "bug_findings": [],
        "security_findings": [],
        "smell_findings": [],
        "generated_tests": [],
        "next_action": "start",
        "critical_found": False,
    }

    typer.echo(f"Starting {mode} review for {tag} ({len(files_to_review)} files)...")

    from .graph.workflow import app_graph

    # Pass project-defined max_iterations to the graph recursion limit
    limit = initial_state["project_config"].get("max_iterations", 25)
    final_state = asyncio.run(
        app_graph.ainvoke(initial_state, {"recursion_limit": limit})
    )

    typer.echo("\n--- REVIEW COMPLETE ---")
    typer.echo(final_state.get("final_report", "No report generated."))
    db.close()


@app.command()
def summary(tag: str = typer.Argument(..., help="Project tag")):
    """Get an AI-generated high-level summary of the entire codebase."""
    db = get_registry_session()
    project = db.query(Project).filter(Project.tag == tag).first()
    if not project:
        typer.echo(f"Error: Project with tag {tag} not found.")
        raise typer.Exit(1)

    project_dir = get_project_dir(tag)
    from .db.ladybug_db import LadybugClient

    client = LadybugClient(db_path=project_dir / "graph_db")

    try:
        # 1. Fetch all directory summaries from KG
        res = client.execute("MATCH (d:Directory) RETURN d.path, d.summary")
        summaries = []
        if res.has_next():
            df = res.get_as_df()
            for _, row in df.iterrows():
                summaries.append(f"Path: {row['d.path']}\nSummary: {row['d.summary']}")

        if not summaries:
            typer.echo("No ingestion data found. Please run 'reverie load' first.")
            raise typer.Exit(1)

        # 2. Synthesize with Gemini
        typer.echo("Synthesizing codebase summary...")
        from langchain_google_genai import ChatGoogleGenerativeAI
        from .core.config import GEMINI_MODEL_TYPE, GEMINI_API_KEY

        llm = ChatGoogleGenerativeAI(
            model=GEMINI_MODEL_TYPE, google_api_key=GEMINI_API_KEY
        )

        all_context = "\n\n".join(summaries)
        prompt = f"""
        You are a Senior Architect. Based on the following directory-level summaries, 
        provide a comprehensive, high-level architectural overview of the project '{project.name}'.
        
        Focus on:
        1. Core purpose of the project.
        2. Key architectural layers and their interactions.
        3. Tech stack and libraries used.
        4. Entry points and main data flows.
        
        DIRECTORY SUMMARIES:
        {all_context}
        """

        response = llm.invoke(prompt)
        typer.echo("\n--- CODEBASE SUMMARY ---")
        typer.echo(response.content)

    except Exception as e:
        typer.echo(f"Error generating summary: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    app()
