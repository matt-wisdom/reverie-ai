# Reverie AI Roadmap & TODO

## 🚀 Immediate Next Steps
- [ ] **TestGenAgent Implementation**: Replace the current stub with a real agent that uses the Knowledge Graph to generate `pytest` or `vitest` cases for identified functions.
- [ ] **Active Vulnerability Scanning**: Build an offensive agent that actively tries to exploit identified vulnerabilities (e.g., generating and executing payloads against a running instance or mock environment to confirm exploitability).
- [ ] **Semgrep Integration**: Fully map Knowledge Graph sinks to Semgrep rules for cross-verification.
- [ ] **Exploit Chaining**: 
- [ ] **LLM Application Testing**: Implement automated evals to benchmark agent accuracy and measure hallucination rates.

## 🛠 Backend Enhancements
- [ ] **Project Registry Cleanup**: Add a CLI command to delete projects and their associated databases.
- [ ] **Diff-Mode API**: Add an endpoint to run reviews on specific git diffs (currently only supported via pre-commit hook).
- [ ] **Incremental Summary Updates**: Update the project-level architectural summary only when files change, rather than full regeneration.
- [ ] **Support for more languages**: Improve tree-sitter queries for Java, Ruby, and PHP.

## 💻 Frontend (GUI) Improvements
- [ ] **File Tree Explorer**: Browse the repository files directly in the browser and see findings highlighted in the code.
- [ ] **Real-time Logs**: Show live streaming logs/thinking process of the agents while a review is running.
- [ ] **SARIF Downloader**: Add a button to download the SARIF report for integration into CI/CD or VS Code extensions.
- [ ] **Project Management**: Allow initializing and loading new projects directly from the UI (uploading paths).
- [ ] **Auth Layer**: Basic local authentication for the dashboard.

## 🔗 Integrations
- [ ] **GitHub Action**: Create a reusable action to run Reverie on PRs automatically.
- [ ] **VS Code Extension**: A companion extension to view findings and architectural summaries inline.

## 🧹 Maintenance
- [ ] **Telemetry/Usage Stats**: (Optional) Track number of findings vs model used for performance tuning.
- [ ] **Documentation**: Complete the `README.md` with full installation and developer guides.
