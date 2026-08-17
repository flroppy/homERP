def test_demo_read_only_blocks_html_create(client, monkeypatch):
    monkeypatch.setattr('config.settings.demo_read_only', True)
    r = client.post('/new/', data={'name': 'Nope', 'content': '', 'label': 'no'},
                    files={'photo': ('', b'', 'application/octet-stream')})
    assert r.status_code == 403


def test_demo_read_only_blocks_api_create(client, monkeypatch):
    monkeypatch.setattr('config.settings.demo_read_only', True)
    r = client.post('/api/items/', json={'name': 'Nope'})
    assert r.status_code == 403


def test_demo_read_only_blocks_delete_attachment(client, item, data_dir, monkeypatch):
    client.post(f'/upload/{item}', files={'file': ('note.txt', b'x', 'text/plain')})
    monkeypatch.setattr('config.settings.demo_read_only', True)
    r = client.post(f'/delete-attachment/{item}/note.txt')
    assert r.status_code == 403
    assert (data_dir / item / 'note.txt').exists()


def test_demo_read_only_allows_reads(client, item, monkeypatch):
    monkeypatch.setattr('config.settings.demo_read_only', True)
    assert client.get('/all-items').status_code == 200
    assert client.get(f'/browse/{item}').status_code == 200
    assert client.get('/api/tree').status_code == 200


def test_demo_read_only_off_by_default_allows_writes(client):
    r = client.post('/api/items/', json={'name': 'Allowed'})
    assert r.status_code == 201
