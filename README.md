# UAX Studio

![UAX Studio — turn product ideas into AI-ready build briefs](docs/assets/uax-studio-social-preview.png)

UAX Studio is a local-first Flask application for turning product ideas, workflows, and source notes into AI-ready Markdown build briefs for apps, agents, websites, automations, and internal tools.

It works without an API key. See the [tutorial](TUTORIAL.md) for a walkthrough from first launch to export.

## Requirements

- Python 3.10 or newer.
- Windows, macOS, or Linux.
- Ollama is optional and only needed for local-model suggestions.

UAX Studio is a single-user local application without accounts or access controls. Keep the default `127.0.0.1` host for normal use.

## MVP Capabilities

- Start in Simple Mode with one brief that generates a build target, feature plan, workflow, acceptance checks, and export path.
- Create, duplicate, archive, restore, and permanently delete local projects.
- Add pasted text or upload TXT, MD, JSON, CSV, PDF, and DOCX sources.
- Generate editable Build Instructions directly from saved Background Information without an API key.
- Optionally choose a detected local Ollama model for structured suggestions with deterministic fallback.
- Edit Brief modules in an accessible side panel and version the full Build Instructions, including target product, implementation details, and agent guardrails when needed.
- Model workflow nodes and edges in a vanilla JavaScript canvas with table parity.
- Run product-quality reviewers and manage findings.
- Export Markdown, JSON, Mermaid, manifest hashes, ZIP bundle, and `AI_BUILD_BRIEF.md`.

## Architecture

The app uses Flask 3, Jinja templates, Flask-SQLAlchemy, SQLite, Pydantic validation, and vanilla JavaScript modules. Route handlers live in `app/routes/main.py`; core behavior lives in `app/services/`.

Projects stay on the local machine. The deterministic provider is the default and never calls a remote model. Ollama is optional and uses its local HTTP API only when a detected local model is selected in Settings. Local data and export directories can be changed from Settings.

## Prompt Customization

Prompt keys are registered in `app/services/prompt_service.py`. The editable prompt text lives in `app/prompts/*.md`. To add a new prompt, add a key and Markdown filename to `PROMPT_FILES`, create the Markdown file, then call `get_prompt("your_key")` where the provider request is made.

## Windows Setup

Open a terminal in the folder containing `run.py`. Double-click `start.bat`, or run these PowerShell commands (activation is optional):

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

Open `http://127.0.0.1:5000`.

## macOS/Linux Setup

From the folder containing `run.py`, run `bash start.sh`, or:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

Open `http://127.0.0.1:5000`.

On first launch, the app creates its SQLite database, local session secret, and fictional GalleryFlow demo. No existing database or personal project data is needed.

## Configuration

The app works without a `.env` file. To override defaults, copy `.env.example` to `.env` and edit the values you need. Real secrets and local settings are excluded from Git.

| Variable | Default | Purpose |
| --- | --- | --- |
| `AX_HOST` | `127.0.0.1` | Local server interface. |
| `AX_PORT` | `5000` | Local server port. |
| `AX_DATABASE_URI` | `sqlite:///ax_studio.sqlite3` | Database URI; the default database lives in `instance/`. |
| `AX_DATA_DIR` | `data` | Parent directory for local uploads and exports. |
| `AX_SECRET_KEY` | generated locally | Optional fixed session secret; leave blank to generate one. |
| `AX_ACTIVE_PROVIDER` | `deterministic` | Suggestion provider. |
| `AX_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama API URL. |
| `AX_OLLAMA_MODEL` | `llama3.1` | Preferred local model. |
| `AX_OLLAMA_TIMEOUT` | `20` | Ollama request timeout in seconds. |
| `AX_AUTO_INIT_DB` | `1` | Initializes and upgrades the database at startup. |

## Tests

Install development dependencies and run the checks used by GitHub Actions:

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m compileall -q app tests run.py
python -m pytest
```

Tests use temporary SQLite databases and temporary data directories.

The suite also runs browser checks when Node 22+ and Microsoft Edge, Chromium, or Chrome are installed. Set `UAX_TEST_BROWSER` to a Chromium browser executable if it is not detected automatically. These checks launch a hidden headless browser with a temporary profile and verify the Brief layout at desktop, tablet, and mobile widths, keyboard and screen-reader heading order, instruction generation, module editing, unsaved-change protection, and Workflow editing. Browser checks are skipped when those tools are unavailable.

## Demo

The app seeds a complete fictional demo named `GalleryFlow: Artist Submission Coordination`.

Reset it with:

```bash
flask --app run.py seed-demo --reset
```

You can also reset it from Settings.

## Ollama

Ollama is optional. In Settings, use `Test local models` to detect local Ollama models from the configured base URL and list them under `Active provider`. Guided project creation, Build Instructions, and quality checks use the selected local model when it is available. If no local model is detected, or if Ollama fails to return valid structured JSON, UAX Studio uses the deterministic provider.

## Supported Uploads

Supported extensions are `.txt`, `.md`, `.json`, `.csv`, `.pdf`, and `.docx`. Individual uploads are limited to 25 MB. Uploaded filenames are never used as storage filenames.

## Local Data

Settings can change the data directory and export directory. Uploads are stored in an `uploads` folder inside the configured data directory, and generated bundles are written to the configured export directory. When either path changes, tracked files are moved with their records. The app rolls the operation back if a move fails.

SQLite schema upgrades run automatically during startup through Alembic migrations. Before upgrading an existing database, UAX Studio creates a timestamped copy under `instance/backups/`.

The repository excludes local databases, session secrets, settings, uploaded files, generated exports, virtual environments, and caches. Empty `.gitkeep` files preserve the default data folders.

## Export Contents

Exports include:

- `README.md`
- `product_intent.md`
- `build_contract.md`
- `agent_experience_contract.md`
- `workflow.md`
- `workflow.mmd`
- `workflow.json`
- `findings.md`
- `acceptance_criteria.md`
- `implementation_manifest.json`
- `AI_BUILD_BRIEF.md`

Sources are excluded unless `Include my source files` is selected. Selected packages preserve original uploads under `sources/originals/` and editable text copies under `sources/text/`.

## Current Limitations

- Ollama quality depends on the locally installed model.
- The workflow canvas is intentionally modest and focused on MVP graph editing.

## Future Opportunities

- Multi-user collaboration.
- Cloud sync.
- Production integrations.
- Figma plugin.
- Browser extension.
- Template marketplace.
- Production agent hosting.

## Troubleshooting

- If port 5000 is busy, set `AX_PORT=5001`.
- If settings are corrupted, remove `instance/settings.json`.
- If the demo needs a clean reset, run `flask --app run.py seed-demo --reset`.
- If uploads fail, confirm the extension is supported and the file is below 25 MB.

## Updating the GitHub Repository

See [GITHUB_UPDATE.md](GITHUB_UPDATE.md) for instructions for updating the existing repository, including obsolete files to remove.

## License and Responsible Use

Copyright © 2026 Joseph Fula and UAX Studio contributors. See the [MIT License](LICENSE), [disclaimer](DISCLAIMER.md), and [third-party notices](THIRD_PARTY_NOTICES.md). Generated planning materials require human review before implementation.
