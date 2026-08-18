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
_status_cache: dict = {"configured": False}


def is_configured() -> bool:
    return bool(settings.git_remote_url)


def ensure_repo(data_dir: Path):
    """Ensure data_dir is a git repo with remote configured. Called at startup."""
    global _status_cache
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

    # Warm the cache so it reflects reality (e.g. changes left over from a
    # previous run) before the app starts serving requests.
    _status_cache = _compute_git_status(data_dir)


def _commit_and_push(data_dir: Path, message: str):
    global _status_cache
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
    finally:
        _status_cache = _compute_git_status(data_dir)


def _build_message(messages: list[str]) -> str:
    if len(messages) == 1:
        return messages[0]
    subject = f"Bulk update ({len(messages)} operations)"
    body = "\n".join(f"- {m}" for m in messages)
    return f"{subject}\n\n{body}"


def _worker():
    """Serialize and debounce git backup operations.

    Waits up to _DEBOUNCE_SECONDS for the queue to go quiet, then commits
    everything staged in one shot. Rapid bursts produce a single commit+push
    with a summary subject and per-operation list in the body.
    """
    global _status_cache
    while True:
        # Block until there is at least one operation to process.
        first_message, data_dir = _backup_queue.get()
        messages = [first_message]
        # Reflect the pending write immediately. Runs here in the background
        # thread rather than in git_auto_backup(), so it never adds a live
        # git walk to the request that triggered it.
        _status_cache = _compute_git_status(data_dir)

        # Drain additional operations that arrive within the debounce window.
        # Each new arrival resets the deadline so the window slides with activity.
        while True:
            deadline = time.monotonic() + _DEBOUNCE_SECONDS
            try:
                msg, _ = _backup_queue.get(timeout=deadline - time.monotonic())
                messages.append(msg)
            except queue.Empty:
                break  # quiet for a full window — commit now

        _commit_and_push(data_dir, _build_message(messages))


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
    """Return the cached git status for the /git-status endpoint and footer indicator.

    Always an instant cache read — never a live git walk. The app is the
    only writer to the data repo, so the cache is only refreshed on the
    events that can actually change it: once at startup, when the backup
    worker picks up a newly queued write (so "pending changes" show up
    right away), and again once the debounced commit+push completes.
    """
    if not is_configured():
        return {"configured": False}
    return _status_cache


def _compute_git_status(data_dir: Path) -> dict:
    try:
        repo = Repo(str(data_dir))
        status = porcelain.status(repo)
        try:
            commits = list(repo.get_walker(max_entries=1))
            last_commit = commits[0].commit.message.decode().strip() if commits else None
        except KeyError:
            last_commit = None  # no commits yet (e.g. before the first backup runs)
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
