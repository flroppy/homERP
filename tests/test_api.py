"""Tests for the REST API (/api/*)."""
from config import settings


# --- Items ---

def test_get_root(client):
    r = client.get('/api/items/')
    assert r.status_code == 200
    data = r.json()
    assert 'children' in data
    assert 'attachments' in data


def test_create_item(client, data_dir):
    r = client.post('/api/items/', json={'name': 'API Box', 'content': 'some notes'})
    assert r.status_code == 201
    body = r.json()
    assert body['name'] == 'API Box'
    assert 'id' in body
    assert (data_dir / 'API Box' / 'index.md').exists()


def test_create_item_nested(client, data_dir):
    client.post('/api/items/', json={'name': 'Container'})
    r = client.post('/api/items/Container', json={'name': 'Widget'})
    assert r.status_code == 201
    assert (data_dir / 'Container' / 'Widget').is_dir()


def test_create_item_conflict(client):
    client.post('/api/items/', json={'name': 'Dupe'})
    r = client.post('/api/items/', json={'name': 'Dupe'})
    assert r.status_code == 409


def test_create_item_missing_parent(client):
    r = client.post('/api/items/nonexistent', json={'name': 'Child'})
    assert r.status_code == 404


def test_get_item(client, item, data_dir):
    r = client.get(f'/api/items/{item}')
    assert r.status_code == 200
    data = r.json()
    assert data['name'] == item
    assert 'id' in data
    assert 'children' in data


def test_get_item_missing(client):
    r = client.get('/api/items/does-not-exist')
    assert r.status_code == 404


def test_update_item_content(client, item, data_dir):
    r = client.patch(f'/api/items/{item}', json={'content': 'updated notes'})
    assert r.status_code == 200
    assert 'updated notes' in (data_dir / item / 'index.md').read_text()


def test_update_item_rename(client, item, data_dir):
    r = client.patch(f'/api/items/{item}', json={'name': 'Renamed'})
    assert r.status_code == 200
    assert (data_dir / 'Renamed').is_dir()
    assert not (data_dir / item).exists()


def test_update_item_rename_conflict(client, data_dir):
    for name in ('Alpha', 'Beta'):
        client.post('/api/items/', json={'name': name})
    r = client.patch('/api/items/Alpha', json={'name': 'Beta'})
    assert r.status_code == 409


def test_delete_item(client, item, data_dir):
    r = client.delete(f'/api/items/{item}')
    assert r.status_code == 204
    assert not (data_dir / item).exists()


def test_delete_item_promotes_children(client, data_dir):
    client.post('/api/items/', json={'name': 'Parent'})
    client.post('/api/items/Parent', json={'name': 'Child'})
    r = client.delete('/api/items/Parent')
    assert r.status_code == 204
    assert not (data_dir / 'Parent').exists()
    assert (data_dir / 'Child').is_dir()


def test_delete_item_missing(client):
    r = client.delete('/api/items/nonexistent')
    assert r.status_code == 404


def test_move_item(client, data_dir):
    client.post('/api/items/', json={'name': 'Container'})
    client.post('/api/items/', json={'name': 'Widget'})
    r = client.post('/api/items/Widget/move', json={'destination': 'Container'})
    assert r.status_code == 200
    assert (data_dir / 'Container' / 'Widget').is_dir()
    assert not (data_dir / 'Widget').exists()


def test_move_item_by_id(client, data_dir):
    client.post('/api/items/', json={'name': 'Dest'})
    client.post('/api/items/', json={'name': 'Mover'})
    dest_id = client.get('/api/items/Dest').json()['id']
    r = client.post('/api/items/Mover/move', json={'destination': dest_id, 'by_id': True})
    assert r.status_code == 200
    assert (data_dir / 'Dest' / 'Mover').is_dir()


# --- Photo ---

def test_upload_photo_jpeg(client, item, data_dir):
    img = b'\xff\xd8\xff\xe0' + b'\x00' * 16  # minimal JPEG-ish bytes
    r = client.post(f'/api/items/{item}/photo',
                    files={'file': ('photo.jpg', img, 'image/jpeg')})
    assert r.status_code == 201
    assert (data_dir / item / 'photo.jpg').exists()


def test_upload_photo_replaces_thumbnail(client, item, data_dir):
    (data_dir / item / 'thumbnail.jpg').write_bytes(b'old')
    img = b'\xff\xd8\xff\xe0' + b'\x00' * 16
    client.post(f'/api/items/{item}/photo',
                files={'file': ('photo.jpg', img, 'image/jpeg')})
    assert not (data_dir / item / 'thumbnail.jpg').exists()


def test_upload_photo_wrong_type(client, item):
    r = client.post(f'/api/items/{item}/photo',
                    files={'file': ('doc.pdf', b'%PDF', 'application/pdf')})
    assert r.status_code == 415


def test_upload_photo_missing_item(client):
    r = client.post('/api/items/nowhere/photo',
                    files={'file': ('photo.jpg', b'', 'image/jpeg')})
    assert r.status_code == 404


def test_get_photo(client, item, data_dir):
    (data_dir / item / 'photo.jpg').write_bytes(b'img')
    r = client.get(f'/api/items/{item}/photo')
    assert r.status_code == 200
    assert r.content == b'img'


def test_get_photo_missing(client, item):
    r = client.get(f'/api/items/{item}/photo')
    assert r.status_code == 404


# --- Print ---

def test_print_no_printer_configured(client, item, monkeypatch):
    monkeypatch.setattr('config.settings.barcode_printer_address', '')
    r = client.post(f'/api/items/{item}/print')
    assert r.status_code == 503


def test_print_item_not_found(client, monkeypatch):
    monkeypatch.setattr('config.settings.barcode_printer_address', 'tcp://127.0.0.1')
    r = client.post('/api/items/nonexistent/print')
    assert r.status_code == 404


# --- Tree ---

def test_tree_returns_nested_structure(client, data_dir):
    client.post('/api/items/', json={'name': 'Room'})
    client.post('/api/items/Room', json={'name': 'Box'})
    r = client.get('/api/tree')
    assert r.status_code == 200
    data = r.json()
    assert 'tree' in data
    assert 'total' in data
    room = next(n for n in data['tree'] if n['name'] == 'Room')
    assert any(c['name'] == 'Box' for c in room['children'])
    assert 'id' in room
    assert 'path' in room


# --- Search ---

def test_search_returns_results(client, item):
    r = client.get(f'/api/search?query={item}')
    assert r.status_code == 200
    data = r.json()
    assert 'results' in data


def test_search_by_id(client, item, data_dir):
    import yaml
    index = (data_dir / item / 'index.md').read_text()
    _, front, _ = index.split('---', 2)
    item_id = yaml.safe_load(front)['id']
    r = client.get(f'/api/search?query={item_id}')
    assert r.status_code == 200
    data = r.json()
    assert data.get('type') == 'id_match'


# --- Attachments ---

def test_upload_attachment(client, item, data_dir):
    r = client.post(f'/api/items/{item}/attachments',
                    files={'file': ('note.txt', b'hello', 'text/plain')})
    assert r.status_code == 201
    body = r.json()
    assert body['name'] == 'note.txt'
    assert body['size'] == 5
    assert (data_dir / item / 'note.txt').exists()


def test_download_attachment(client, item, data_dir):
    content = b'file content'
    client.post(f'/api/items/{item}/attachments',
                files={'file': ('doc.txt', content, 'text/plain')})
    r = client.get(f'/api/items/{item}/attachments/doc.txt')
    assert r.status_code == 200
    assert r.content == content


def test_delete_attachment(client, item, data_dir):
    client.post(f'/api/items/{item}/attachments',
                files={'file': ('del.txt', b'x', 'text/plain')})
    r = client.delete(f'/api/items/{item}/attachments/del.txt')
    assert r.status_code == 204
    assert not (data_dir / item / 'del.txt').exists()


def test_download_attachment_missing(client, item):
    r = client.get(f'/api/items/{item}/attachments/nope.txt')
    assert r.status_code == 404


def test_attachment_in_item_response(client, item, data_dir):
    client.post(f'/api/items/{item}/attachments',
                files={'file': ('info.txt', b'data', 'text/plain')})
    r = client.get(f'/api/items/{item}')
    names = [a['name'] for a in r.json()['attachments']]
    assert 'info.txt' in names


# --- API key authentication ---

def test_api_key_disabled_by_default(client):
    r = client.get('/api/items/')
    assert r.status_code == 200


def test_api_key_rejects_missing_key(client, monkeypatch):
    monkeypatch.setattr(settings, 'api_key', 'secret')
    r = client.get('/api/items/')
    assert r.status_code == 401


def test_api_key_rejects_wrong_key(client, monkeypatch):
    monkeypatch.setattr(settings, 'api_key', 'secret')
    r = client.get('/api/items/', headers={'X-API-Key': 'wrong'})
    assert r.status_code == 401


def test_api_key_accepts_correct_key(client, monkeypatch):
    monkeypatch.setattr(settings, 'api_key', 'secret')
    r = client.get('/api/items/', headers={'X-API-Key': 'secret'})
    assert r.status_code == 200
