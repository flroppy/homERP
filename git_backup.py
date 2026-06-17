import asyncio
import logging
from pathlib import Path
from dulwich import porcelain
from dulwich.repo import Repo
from dulwich.errors import NotGitRepository
from config import settings

logger = logging.getLogger(__name__)

GITIGNORE_CONTENT = "thumbnail.jpg\n"


def is_configured() -> bool:
    return bool(settings.git_remote_url)


def ensure_repo(data_dir: Path):
    """Ensure data_dir is a git repo with remote configured. Called at startup."""
    if not is_configured():
        return

    gitignore = data_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE_CONTENT)

    try:
        repo = Repo(str(data_dir))
    except NotGitRepository:
        repo = porcelain.init(str(data_dir))
        logger.info("Initialised git repo at %s", data_dir)

    # Set or update remote
    config = repo.get_config()
    remote_url = settings.git_remote_url.encode()
    config.set((b"remote", b"origin"), b"url", remote_url)
    config.write_to_path()


def _commit_and_push(data_dir: Path, message: str):
    """Commit all changes and push. Runs in a thread."""
    try:
        repo = Repo(str(data_dir))
        porcelain.add(repo)
        porcelain.commit(
            repo,
            message=message.encode(),
            author=settings.git_author.encode(),
            committer=settings.git_author.encode(),
        )
        porcelain.push(
            repo,
            remote_location=settings.git_remote_url,
            username=settings.git_username or None,
            password=settings.git_token or None,
        )
        logger.info("Git backup: %s", message)
    except Exception:
        logger.exception("Git backup failed (message: %s)", message)


def git_auto_backup(operation: str, item_name: str, relative_path: str, data_dir: Path):
    """Fire-and-forget commit+push. Never raises — failures are logged only."""
    if not is_configured():
        return

    messages = {
        "create": f"Add new item: {item_name} at {relative_path}",
        "update": f"Update item: {item_name} at {relative_path}",
        "delete": f"Delete item: {item_name} from {relative_path}",
        "move": f"Move item: {item_name} to {relative_path}",
        "upload": f"Upload attachment to {item_name} at {relative_path}",
        "delete_attachment": f"Delete attachment from {item_name} at {relative_path}",
    }
    message = messages.get(operation, f"Change to {item_name} at {relative_path}")

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _commit_and_push, data_dir, message)


def git_status(data_dir: Path) -> dict:
    """Return current git status for the /git-status endpoint."""
    if not is_configured():
        return {"configured": False}
    try:
        repo = Repo(str(data_dir))
        status = porcelain.status(repo)

        # porcelain.log() prints to stdout by default; use the walker directly
        commits = list(repo.get_walker(max_entries=1))
        last_commit = commits[0].commit.message.decode().strip() if commits else None

        staged = status.staged or {}
        return {
            "configured": True,
            "last_commit": last_commit,
            "staged": [f.decode() for f in (
                staged.get(b"add", []) + staged.get(b"modify", []) + staged.get(b"delete", [])
            )],
            "unstaged": [f.decode() for f in (status.unstaged or [])],
            "untracked": [f.decode() for f in (status.untracked or [])],
        }
    except Exception as e:
        return {"configured": True, "error": str(e)}
