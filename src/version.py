"""Resolve the running app's version for display in the UI footer."""

import os
from pathlib import Path
from typing import Optional

from dulwich.errors import NotGitRepository
from dulwich.repo import Repo

_REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_URL = "https://github.com/flroppy/homERP"


def get_version() -> tuple[str, Optional[str]]:
    """Version string and its source-repo link, for the footer.

    On a tagged release build, VERSION is baked in as the git tag (e.g.
    "v1.2.0") and links to that tag's source tree. Otherwise falls back to
    the short commit SHA baked in as GIT_SHA (both set at Docker build
    time, since .git itself isn't shipped in the container) linked to its
    commit page. For `uvicorn --reload` dev runs where neither is set,
    falls back to reading the local checkout's HEAD directly via dulwich.
    """
    tag = os.getenv("VERSION")
    if tag:
        return tag, f"{SOURCE_URL}/src/tag/{tag}"

    sha = os.getenv("GIT_SHA")
    if sha:
        sha = sha[:7]
        return sha, f"{SOURCE_URL}/commit/{sha}"

    try:
        with Repo(str(_REPO_ROOT)) as repo:
            sha = repo.head().decode()[:7]
            return sha, f"{SOURCE_URL}/commit/{sha}"
    except (NotGitRepository, KeyError):
        return "unknown", None


VERSION, VERSION_URL = get_version()
