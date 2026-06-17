import pytest
from fastapi.testclient import TestClient
import main
import git_backup


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Redirect HOUSE_ROOT to a fresh temp directory for each test."""
    monkeypatch.setattr(main, 'HOUSE_ROOT', tmp_path)
    (tmp_path / 'index.md').write_text('---\nid: testhome\n---\n')
    monkeypatch.setattr(main, 'send_to_printer', lambda img: None)
    monkeypatch.setattr(git_backup, 'git_auto_backup', lambda *a, **kw: None)
    return tmp_path


@pytest.fixture
def client(data_dir):
    return TestClient(main.app, follow_redirects=True)


@pytest.fixture
def item(data_dir, client):
    """Create a single item and return its name."""
    name = 'Test Box'
    client.post('/create/', data={'name': name, 'content': 'stuff inside', 'go': 'true', 'label': 'no'},
                files={'photo': ('photo.jpg', b'', 'image/jpeg')})
    return name
