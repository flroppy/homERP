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
- Docker deployment with docker-compose
- No formal testing setup