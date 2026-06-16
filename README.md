# 🐞 Reverie AI

**Reverie AI** is a multi-agent, graph-augmented code review system designed to identify deep logic bugs, security vulnerabilities, and architectural smells across large codebases. Unlike standard "chat with your code" tools, Reverie pre-compiles your repository into a **Knowledge Graph** to perform cross-file taint analysis and structural reasoning.

---

## ✨ Key Features

*   **Multi-Agent Orchestration**: Coordinate specialized agents (Security, Bug, Smell) in parallel via LangGraph.
*   **Knowledge Graph (GAG)**: Map function calls, class hierarchies, and imports across your entire repo using `tree-sitter` and `LadybugDB`.
*   **Taint Analysis**: Track data flow from entry points (API routes) to dangerous sinks across file boundaries.
*   **Unified Provider Support**: Supports 100+ LLM providers (Gemini, OpenAI, Anthropic, Groq, Ollama, etc.) via **LiteLLM**.
*   **Modern GUI**: A Vue.js dashboard to manage projects, trigger reviews, and view beautifully formatted Markdown reports.
*   **Lightweight Pre-commit Hook**: A sub-5s local check that runs on staged files before you commit.

---

## 🛠 Tech Stack

-   **Backend**: Python 3.13, FastAPI, SQLAlchemy, LangGraph.
-   **AI Orchestration**: LangChain, LangGraph, **LiteLLM**.
-   **Parsing**: Tree-sitter (multi-language support).
-   **Storage**: LadybugDB (Knowledge Graph), ChromaDB (Vector Store), SQLite (Registry).
-   **Frontend**: Vue 3, Vite, Pinia, Vanilla CSS.

---

## 🚀 Getting Started

### 1. Prerequisites
-   Python 3.13+
-   Node.js (for building the frontend)
-   `uv` (recommended Python package manager)

### 2. Installation
Clone the repo and install the CLI globally:
```bash
uv tool install ./reverie --force --no-cache
```

### 3. Configuration (LiteLLM)
Reverie uses a unified configuration format: `provider/model_name`. Create your global settings:

```bash
mkdir -p ~/.reverie
cat <<EOF > ~/.reverie/.env
# Example for OpenAI
LLM_MODEL=openai/gpt-4o
LLM_API_KEY=your_openai_key

# Example for Gemini (default)
# LLM_MODEL=gemini/gemini-1.5-flash
# LLM_API_KEY=your_gemini_key

EMBEDDING_MODEL=openai/text-embedding-3-small
EMBEDDING_API_KEY=your_openai_key

TAVILY_API_KEY=your_tavily_key
EOF
```

---

## 💻 CLI Reference

Reverie provides a powerful CLI for automation and integration.

### Core Commands

#### `reverie init <PATH>`
Initialize a new project registry entry.
*   **Arguments**: `PATH` (Path to the local repository).
*   **Options**:
    *   `--tag <TAG>`: Unique identifier for the project (e.g., `my-api`).
    *   `--min-severity <level>`: Threshold for findings (low, medium, high). Default: `medium`.

#### `reverie load <TAG>`
Ingest the codebase into the Knowledge Graph and Vector Database.
*   **Arguments**: `TAG` (Project unique identifier).
*   **Options**:
    *   `--force`, `-f`: Ignore hashes and re-ingest all files.
    *   `--prompt`, `-p`: Custom instructions to influence the AI-generated architectural summary.

#### `reverie summary <TAG>`
Retrieve the AI-generated high-level architectural overview of the codebase.

#### `reverie review <TAG>`
Execute the multi-agent reasoning loop.
*   **Options**:
    *   `--mode <MODES>`: Comma-separated list of agents to run (`bug_detect`, `security`, `smell`). Default: `full`.
    *   `--prompt`, `-p`: Custom instructions injected into agent personas for this specific run.
    *   `--output-dir`, `-o`: Custom path to export Markdown and SARIF reports.

#### `reverie server`
Launch the GUI and REST API.
*   **Options**: `--host`, `--port`, `--reload`. Default: `http://127.0.0.1:8000`.

---

### Specialized Tools

#### `reverie hook`
Manage git pre-commit hooks for automated safety.
*   **`install <TAG>`**: Adds a script to `.git/hooks/pre-commit` that runs security and smell checks on staged files.
*   **`uninstall <TAG>`**: Safely removes the Reverie hook.
*   **`run <TAG>`**: Manually triggers the fast-pass check on staged files.

#### `reverie history`
Manage and view previous review reports.
*   **`list <TAG>`**: Show all historical run IDs and timestamps.
*   **`get-report <TAG> <ID>`**: Output the Markdown content of a specific report to the terminal.
*   **`get-sarif <TAG> <ID>`**: Output the SARIF JSON content of a specific report.

---

## 🌐 GUI Usage

Reverie includes a built-in web dashboard for visual reporting and management.


### 1. Start the Server
```bash
reverie server
```

---

## 🔍 How it Works: The Security Agent

1.  **Context Retrieval**: Injects relevant security rules from the Vector DB into the agent's prompt.
2.  **Investigation Plan**: The agent identifies entry points and dangerous sinks in the target file.
3.  **Graph Walking**: Uses `get_data_flow` and `get_callers` to trace "tainted" user input across file boundaries.
4.  **Verification**: Confirms exploitability by reading relevant files and checking sanitization logic.
5.  **Emission**: Vulnerabilities are exported with severity, CWE IDs, and remediation steps.

---

## 🗺 Roadmap

- [ ] **Real Test Generation**: Implement `TestGenAgent` using Knowledge Graph context.
- [ ] **Active Scanning**: Automated exploit generation and verification (offensive agent that confirms findings).
- [ ] **File Tree Explorer**: Browse repository findings inline in the browser.
- [ ] **LLM Evals**: Automated accuracy benchmarking for agent reasoning.

---

## 📜 License
MIT
