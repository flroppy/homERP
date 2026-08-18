# homERP

[![Tests](https://github.com/flroppy/homERP/actions/workflows/tests.yml/badge.svg)](https://github.com/flroppy/homERP/actions)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](LICENSE)

This is a home ERP system for tracking storage of evergreen items in the household. The goal is to give every item a place, so every item can be in its place.

## Setup

**Requirements:** Python 3.10+, `libdmtx` system library (for barcode generation)

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your settings
uvicorn src.main:app --host 0.0.0.0 --port 80 --reload
```

### Try it with example data

The `example/` folder has a small sample inventory (nested items, custom fields, markdown
content) so you can poke around without setting up your own data first:

```bash
DATA_DIR=example uvicorn src.main:app --reload
```

If you're hosting this publicly as a demo, set `DEMO_READ_ONLY=true` — it blocks every
create/edit/delete/upload/move across both the HTML UI and `/api/*` with a 403, so visitors
can look around without being able to touch the data. It only blocks writes; it doesn't
sandbox anything else, so don't point a public demo at data you care about either way.

### Configuration

All settings are environment variables, read from `.env`. The minimum you need to change is `DATA_DIR` — everything else has working defaults.

| Variable | Default | Description |
|---|---|---|
| `DATA_DIR` | `House` | Path to the directory where item data is stored |
| `DEMO_READ_ONLY` | `false` | Block all writes (HTML UI + `/api/*`) — for hosting a public demo |
| `BARCODE_PRINTER_MODEL` | `QL-810W` | Brother QL printer model |
| `BARCODE_PRINTER_ADDRESS` | _(empty)_ | Printer address e.g. `tcp://192.168.1.50`; leave empty to disable printing |
| `BARCODE_PRINTER_TAPE` | `12` | Tape width in mm |
| `BARCODE_RENDERED_HEIGHT` | `106` | Barcode image height in pixels (matches tape width) |
| `GIT_REMOTE_URL` | _(empty)_ | Remote git URL for auto-backup; leave empty to disable |
| `GIT_USERNAME` | _(empty)_ | Git username for HTTPS auth |
| `GIT_TOKEN` | _(empty)_ | Personal access token for HTTPS auth |
| `GIT_AUTHOR` | `homERP <homerp@example.com>` | Git author for backup commits |

### Git backup

Every create/edit/delete/move/upload automatically commits and pushes to a remote git repo. Setup takes about 5 minutes:

1. Create a repo on Gitea, GitHub, etc.
2. Generate a personal access token with repo write access
3. Add to `.env`:
   ```
   GIT_REMOTE_URL=https://gitea.example.com/user/house.git
   GIT_USERNAME=myuser
   GIT_TOKEN=mytoken
   GIT_AUTHOR=My Name <me@example.com>
   ```
4. Rebuild/restart the container
5. Done — check `GET /git-status` to confirm it's working

Leave `GIT_REMOTE_URL` empty to disable backup entirely (the default).

### Docker

```bash
cp .env.example .env
# Edit .env
docker-compose up -d
```

This pulls the prebuilt image from `ghcr.io/flroppy/homerp:latest` rather than building
locally. Three image tags are published:

- `:latest` — the most recent tagged release. What `docker-compose.yaml` uses by default.
- `:git` — rebuilt on every push to main, for tracking unreleased changes.
- `:vX.Y.Z` — a specific release, for pinning a deployment to a known version.

To cut a versioned release, push a tag matching `v*` (e.g. `git tag v1.2.0 && git push origin
v1.2.0`) — CI builds and pushes `ghcr.io/flroppy/homerp:v1.2.0` and re-tags `:latest` to
match.

For deployment-specific tweaks (reverse proxy labels, custom networks, running the `example/`
data read-only as a public demo, etc.), add a `docker-compose.override.yml` (gitignored) —
Compose merges it in automatically.

## Goals
These should always be thought about when implementing something
* Reduce friction as much as possible
  * No one will use it if it's hard to use
* Allow for maximum flexibility
  * Items and things are all shapes and sizes and will have different needs for what we want to save about them
  * This manifests by keeping "item" very general
  * The only required data is folder name and id
  * *Any* data can be stored about an item, manifested by arbitrary attachments
* Portable
  * All data stored should be extremely portable
  * This is currently implemented by having everything stored as a raw folder/file on the file system that can easily be manipulated by the user or backed up

## Items

Every item is a folder with metadata (files) and other items (folders) rendered with index.md for metadata
The index.md is rendered as HTML on the parts page and may have any information desired in it for reference.

## ID

ID is a base 64, 8 character long code. This allows for `281474976710656` unique items. IDs are randomly generated but checked for uniqueness.

Since folder names are just the non-unique name, this means there could be conflicts.

## Photo

All items *may* have a `photo.jpg` that will be used for thumbnails and will display on the item page. This should be used to allow for faster navigation as well as reminding you wtf "screws" means 5 years from now

## Attachments

Items may have an arbitrary amount of attachments that will be available for download on the items page. PDFs can be displayed in line for easy manual and document viewing. .md attachments can also be rendered as HTML inline for reference.

## License

[Unlicense](LICENSE) — public domain.

