import sys
from pathlib import Path

# main.py and its sibling modules (storage, config, routers, ...) use flat,
# same-directory imports (e.g. `import storage`) rather than package-relative
# ones. Adding this directory to sys.path lets those imports resolve when the
# app is launched as `uvicorn src.main:app` from the repo root, without
# needing `--app-dir src`.
sys.path.insert(0, str(Path(__file__).parent))
