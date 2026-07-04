import logging
import queue
import threading
import time
from pathlib import Path
from dulwich import porcelain
from dulwich.repo import Repo
from dulwich.errors import NotGitRepository
from config import settings

logger = logging.getLogger(__name__)

GITIGNORE_CONTENT = "thumbnail.jpg\n"
_DEBOUNCE_SECONDS = 60.0

_backup_queue: queue.Queue = queue.Queue()


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

    config = repo.get_config()
    remote_url = settings.git_remote_url.encode()
    config.set((b"remote", b"origin"), b"url", remote_url)
    config.write_to_path()


def _commit_and_push(data_dir: Path, message: str):
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


def _worker():
    """Serialize and debounce git backup operations.

    Waits up to _DEBOUNCE_SECONDS for the queue to go quiet, then commits
    everything staged in one shot. Rapid bursts produce a single commit+push.
    """
    while True:
        # Block until there is at least one operation to process.
        message, data_dir = _backup_queue.get()

        # Drain additional operations that arrive within the debounce window.
        # Each new arrival resets the deadline so the window slides with activity.
        while True:
            deadline = time.monotonic() + _DEBOUNCE_SECONDS
            try:
                msg, _ = _backup_queue.get(timeout=deadline - time.monotonic())
                message = msg  # keep the latest; git add will stage all changes anyway
            except queue.Empty:
                break  # quiet for a full window — commit now

        _commit_and_push(data_dir, message)


threading.Thread(target=_worker, daemon=True, name="git-backup").start()


def git_auto_backup(operation: str, item_name: str, relative_path: str, data_dir: Path):
    """Queue a commit+push. Returns immediately; never raises."""
    if not is_configured():
        return

    messages = {
        "create": f"Add new item: {item_name} at {relative_path}",
        "update": f"Update item: {item_name} at {relative_path}",
        "delete": f"Delete item: {item_name} from {relative_path}",
        "move": f"Move item: {item_name} to {relative_path}",
        "upload": f"Upload attachment to {item_name} at {relative_path}",
        "delete_attachment": f"Delete attachment from {item_name} at {relative_path}",
        "rename_attachment": f"Rename attachment in {item_name} at {relative_path}",
    }
    message = messages.get(operation, f"Change to {item_name} at {relative_path}")
    _backup_queue.put((message, data_dir))


def git_status(data_dir: Path) -> dict:
    """Return current git status for the /git-status endpoint."""
    if not is_configured():
        return {"configured": False}
    try:
        repo = Repo(str(data_dir))
        status = porcelain.status(repo)
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
