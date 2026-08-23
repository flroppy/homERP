# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Run Commands
- Run app: `uvicorn src.main:app --host "0.0.0.0" --port 80 --reload`
- Docker: `docker-compose up -d`
- Run tests: `env/bin/pytest tests/ -v`

## Code Style Guidelines
- Imports: Standard library first, third-party next, function imports last
- Formatting: 4-space indentation, line length ~100 chars
- Naming: snake_case for variables/functions, PascalCase for classes, UPPER_CASE for constants
- Error handling: Use explicit try/except blocks, return None or raise HTTPException with status codes
- Types: Type hints encouraged but not strictly enforced
- Documentation: Write docstrings for public functions and modules
- Structure: Use FastAPI routing patterns, Jinja2 templates in src/templates/
- Data: YAML front matter in markdown files for data storage
- Vim folding markers used (/* vim: ... */)

## Project Organization
- Application code lives under `src/` (`main.py`, `config.py`, `storage.py`, `barcode.py`, `git_backup.py`, `routers/`, `templates/`, `static/`); tests stay at the repo root and pick up `src/` via `pythonpath` in `pytest.ini`. One-off admin scripts (`generate_barcodes.py`, `import_grocy.py`, `mcp_server.py`) live in `scripts/`.
- FastAPI app with file-based storage using YAML/markdown
- HTML templates in `src/templates/` directory
- `src/config.py` holds all configuration via `pydantic-settings` (reads from `.env`)
- Docker deployment with docker-compose
- No formal testing setup

## Configuration
All runtime config lives in `src/config.py` as a `pydantic-settings` `Settings` class. Values are read from environment variables or a `.env` file. Copy `.env.example` to `.env` to get started. Key variables:
- `DATA_DIR` — path to item storage directory (default: `House`)
- `BARCODE_PRINTER_ADDRESS` — printer address e.g. `tcp://192.168.1.x`; leave empty to disable printing
- `BARCODE_PRINTER_MODEL`, `BARCODE_PRINTER_TAPE`, `BARCODE_RENDERED_HEIGHT` — label maker settings
- `GIT_REMOTE_URL`, `GIT_USERNAME`, `GIT_TOKEN`, `GIT_AUTHOR` — git backup settings (implemented via `src/git_backup.py`/dulwich)
- `API_KEY` — API key for the `src/routers/api.py` endpoints
- `DEMO_READ_ONLY` — blocks all writes (HTML UI + `/api/*`) via a middleware in `src/main.py`; default `false`

The printer backend is initialized lazily (only on first print), so the app starts cleanly with no printer configured.

`GROCY_API_KEY` and `GROCY_BASE_URL` are read directly via `os.getenv` in `scripts/import_grocy.py` and are not part of `config.py`'s `Settings`.

## Planned Work
Tracked as [GitHub issues](https://github.com/flroppy/homERP/issues) — that is the source of truth for planned features and refactors, not this file.