"""Tests for git status caching (homERP#15)."""

import time

import git_backup


def test_git_status_not_configured_by_default():
    assert git_backup.git_status(None) == {"configured": False}


def test_git_status_reads_cache_without_recomputing(monkeypatch):
    monkeypatch.setattr('config.settings.git_remote_url', 'git@example.com:x/y.git')
    monkeypatch.setattr(git_backup, '_status_cache', {"configured": True, "last_commit": "cached"})

    def _boom(data_dir):
        raise AssertionError("git_status should read the cache, not recompute")

    monkeypatch.setattr(git_backup, '_compute_git_status', _boom)

    assert git_backup.git_status(None) == {"configured": True, "last_commit": "cached"}


def test_commit_and_push_refreshes_cache_on_failure(monkeypatch, tmp_path):
    monkeypatch.setattr('config.settings.git_remote_url', 'git@example.com:x/y.git')
    monkeypatch.setattr(git_backup, '_status_cache', {"configured": False})
    monkeypatch.setattr(git_backup, '_compute_git_status', lambda data_dir: {"configured": True, "refreshed": True})

    git_backup._commit_and_push(tmp_path, "irrelevant, repo doesn't exist")

    assert git_backup._status_cache == {"configured": True, "refreshed": True}


def test_worker_refreshes_cache_as_soon_as_a_write_is_queued(monkeypatch, tmp_path):
    """No polling: the background worker updates the cache the moment it
    picks a queued write off _backup_queue, before the debounce wait even
    starts, so "pending changes" appear without waiting on a timer."""
    monkeypatch.setattr('config.settings.git_remote_url', 'git@example.com:x/y.git')
    monkeypatch.setattr(git_backup, '_status_cache', {"configured": False})
    monkeypatch.setattr(git_backup, '_DEBOUNCE_SECONDS', 60.0)  # keep the commit from firing mid-assert

    calls = []

    def _fake_compute(data_dir):
        calls.append(data_dir)
        return {"configured": True, "call_count": len(calls)}

    monkeypatch.setattr(git_backup, '_compute_git_status', _fake_compute)

    git_backup.git_auto_backup('create', 'Thing', 'Thing', tmp_path)

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not calls:
        time.sleep(0.01)

    assert calls, "worker never refreshed the cache after picking up the queued write"
    assert git_backup._status_cache == {"configured": True, "call_count": 1}
