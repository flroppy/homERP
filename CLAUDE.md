# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Run Commands
- Run app: `uvicorn main:app --host "0.0.0.0" --port 80 --reload`
- Docker: `docker-compose up -d`

## Code Style Guidelines
- Imports: Standard library first, third-party next, function imports last
- Formatting: 4-space indentation, line length ~100 chars
- Naming: snake_case for variables/functions, PascalCase for classes, UPPER_CASE for constants
- Error handling: Use explicit try/except blocks, return None or raise HTTPException with status codes
- Types: Type hints encouraged but not strictly enforced
- Documentation: Write docstrings for public functions and modules
- Structure: Use FastAPI routing patterns, Jinja2 templates in templates/
- Data: YAML front matter in markdown files for data storage
- Vim folding markers used (/* vim: ... */)

## Project Organization
- FastAPI app with file-based storage using YAML/markdown
- HTML templates in templates/ directory
- `config.py` holds all configuration via `pydantic-settings` (reads from `.env`)
- Docker deployment with docker-compose
- No formal testing setup

## Configuration
All runtime config lives in `config.py` as a `pydantic-settings` `Settings` class. Values are read from environment variables or a `.env` file. Copy `.env.example` to `.env` to get started. Key variables:
- `DATA_DIR` — path to item storage directory (default: `House`)
- `BARCODE_PRINTER_ADDRESS` — printer address e.g. `tcp://192.168.1.x`; leave empty to disable printing
- `BARCODE_PRINTER_MODEL`, `BARCODE_PRINTER_TAPE`, `BARCODE_RENDERED_HEIGHT` — label maker settings
- `GIT_SSH_URL`, `GIT_AUTHOR` — git backup settings (not yet implemented)
- `GROCY_API_KEY` — Grocy integration key

The printer backend is initialized lazily (only on first print), so the app starts cleanly with no printer configured.

## Desired Refactors
- `main.py` is a monolith and should be split into focused modules, e.g.:
  - `routers/items.py` — browse/create/edit/delete/move routes
  - `routers/barcodes.py` — barcode and printing routes
  - `storage.py` — file I/O helpers (`read_index_file`, `list_directory_items`, etc.)
  - `barcode.py` — barcode generation logic
  - `config.py` is already extracted as the first step of this split