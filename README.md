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
# LLM_MODEL=gemini/gemini-3.1-pro
# LLM_API_KEY=your_gemini_key

EMBEDDING_MODEL=openai/text-embedding-3-small
EMBEDDING_API_KEY=your_openai_key

TAVILY_API_KEY=your_tavily_key
EOF
```

---

## 💻 CLI Usage

### Initialize a Project
```bash
reverie init /path/to/your/repo --tag my-project
```

### Ingest the Codebase
Build the Knowledge Graph and Vector index:
```bash
reverie load my-project
```

### Run a Review
```bash
# Run a full review
reverie review my-project

# Run a subset of modes with custom instructions
reverie review my-project --mode security,bug_detect --prompt "Focus on JWT validation logic."
```

### Manage Git Hooks
```bash
reverie hook install my-project
```

---

## 🌐 GUI Usage

Reverie includes a built-in web dashboard for visual reporting and management.

### 1. Build the Frontend
```bash
cd frontend
npm install
npm run build
# Move to backend static folder
rm -rf ../reverie/app/static && cp -r dist ../reverie/app/static
```

### 2. Start the Server
```bash
reverie server
```
Access the dashboard at `http://localhost:8000`.

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
