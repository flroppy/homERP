"""Tests for item CRUD, search, attachments, and move."""


# --- Navigation ---

def test_root_redirects_to_all_items(client):
    r = client.get('/')
    assert r.status_code == 200
    assert 'all-items' in str(r.url)


def test_all_items(client):
    r = client.get('/all-items')
    assert r.status_code == 200


def test_browse_root(client):
    r = client.get('/browse/')
    assert r.status_code == 200


# --- Create ---

def test_create_item(client, data_dir):
    r = client.post('/new/', data={'name': 'My Shelf', 'content': '', 'label': 'no'},
                    files={'photo': ('', b'', 'application/octet-stream')})
    assert r.status_code == 200
    assert (data_dir / 'My Shelf' / 'index.md').exists()


def test_create_strips_trailing_spaces(client, data_dir):
    r = client.post('/new/', data={'name': 'Trimmed  ', 'content': '', 'label': 'no'},
                    files={'photo': ('', b'', 'application/octet-stream')})
    assert r.status_code == 200
    assert (data_dir / 'Trimmed' / 'index.md').exists()
    assert not (data_dir / 'Trimmed  ').exists()


def test_create_empty_content(client, data_dir):
    r = client.post('/new/', data={'name': 'Empty Content', 'content': '', 'label': 'no'},
                    files={'photo': ('', b'', 'application/octet-stream')})
    assert r.status_code == 200
    assert (data_dir / 'Empty Content' / 'index.md').exists()


def test_create_duplicate_name_rejected(client, data_dir):
    client.post('/new/', data={'name': 'Dupe', 'content': '', 'label': 'no'},
                files={'photo': ('', b'', 'application/octet-stream')})
    r = client.post('/new/', data={'name': 'Dupe', 'content': '', 'label': 'no'},
                    files={'photo': ('', b'', 'application/octet-stream')})
    assert r.status_code == 409


def test_create_stays_on_page(client, data_dir):
    """Creating an item should redirect back to /new/ with ?added=."""
    r = client.post('/new/', data={'name': 'Box', 'content': '', 'label': 'no'},
                    files={'photo': ('', b'', 'application/octet-stream')})
    assert r.status_code == 200
    assert 'new' in str(r.url)
    assert 'added=' in str(r.url)


# --- Browse ---

def test_browse_item(client, item):
    r = client.get(f'/browse/{item}')
    assert r.status_code == 200
    assert item in r.text


def test_browse_missing_returns_404(client):
    r = client.get('/browse/does-not-exist')
    assert r.status_code == 404


# --- Edit / Save ---

def test_edit_form(client, item):
    r = client.get(f'/edit/{item}')
    assert r.status_code == 200
    assert item in r.text


def test_save_item(client, item, data_dir):
    r = client.post(f'/save/{item}', data={'name': item, 'content': 'updated content'},
                    files={'photo': ('photo.jpg', b'', 'image/jpeg')})
    assert r.status_code == 200
    index = (data_dir / item / 'index.md').read_text()
    assert 'updated content' in index


def test_save_renames_item(client, item, data_dir):
    r = client.post(f'/save/{item}', data={'name': 'Renamed Box', 'content': ''},
                    files={'photo': ('photo.jpg', b'', 'image/jpeg')})
    assert r.status_code == 200
    assert (data_dir / 'Renamed Box').is_dir()
    assert not (data_dir / item).exists()


def test_save_rename_to_existing_rejected(client, data_dir):
    for name in ('Alpha', 'Beta'):
        client.post('/new/', data={'name': name, 'content': '', 'label': 'no'},
                    files={'photo': ('', b'', 'application/octet-stream')})
    r = client.post('/save/Alpha', data={'name': 'Beta', 'content': ''},
                    files={'photo': ('photo.jpg', b'', 'image/jpeg')})
    assert r.status_code == 409
    assert (data_dir / 'Alpha').is_dir()


def test_save_strips_trailing_spaces(client, item, data_dir):
    r = client.post(f'/save/{item}', data={'name': 'Spaced  ', 'content': ''},
                    files={'photo': ('photo.jpg', b'', 'image/jpeg')})
    assert r.status_code == 200
    assert (data_dir / 'Spaced').is_dir()
    assert not (data_dir / 'Spaced  ').exists()


# --- Delete ---

def test_delete_item(client, item, data_dir):
    r = client.post(f'/delete/{item}')
    assert r.status_code == 200
    assert not (data_dir / item).exists()


def test_delete_moves_children_to_parent(client, data_dir):
    for name in ('Parent', 'Child'):
        client.post('/new/', data={'name': name, 'content': '', 'label': 'no'},
                    files={'photo': ('', b'', 'application/octet-stream')})
    client.post('/move/Child', data={'destination': 'Parent', 'by_id': ''})
    assert (data_dir / 'Parent' / 'Child').is_dir()
    client.post('/delete/Parent')
    assert not (data_dir / 'Parent').exists()
    assert (data_dir / 'Child').is_dir()


def test_delete_root_forbidden(client):
    r = client.post('/delete/')
    assert r.status_code in (400, 422, 500)


# --- Search ---

def test_search_by_name(client, item):
    r = client.get(f'/search?query={item}')
    assert r.status_code == 200
    assert item in r.text


def test_search_by_id(client, item, data_dir):
    import yaml
    index = (data_dir / item / 'index.md').read_text()
    _, front, _ = index.split('---', 2)
    item_id = yaml.safe_load(front)['id']
    r = client.get(f'/search?query={item_id}')
    # Should redirect straight to the item
    assert r.status_code == 200
    assert item in r.text


# --- By ID ---

def test_by_id_redirects(client, item, data_dir):
    import yaml
    index = (data_dir / item / 'index.md').read_text()
    _, front, _ = index.split('---', 2)
    item_id = yaml.safe_load(front)['id']
    r = client.get(f'/by-id/{item_id}')
    assert r.status_code == 200
    assert item in r.text


def test_by_id_missing_returns_404(client):
    r = client.get('/by-id/notanid1')
    assert r.status_code == 404


# --- Attachments ---

def test_upload_and_download_attachment(client, item, data_dir):
    content = b'hello world'
    r = client.post(f'/upload/{item}', files={'file': ('note.txt', content, 'text/plain')})
    assert r.status_code == 200
    assert (data_dir / item / 'note.txt').exists()

    r = client.get(f'/download/{item}/note.txt')
    assert r.status_code == 200
    assert r.content == content


def test_delete_attachment(client, item, data_dir):
    client.post(f'/upload/{item}', files={'file': ('note.txt', b'x', 'text/plain')})
    r = client.get(f'/delete-attachment/{item}/note.txt')
    assert r.status_code == 200
    assert not (data_dir / item / 'note.txt').exists()


def test_download_path_traversal_blocked(client, data_dir):
    r = client.get('/download/../conftest.py')
    assert r.status_code in (400, 403, 404)


def test_view_attachment_inline(client, item, data_dir):
    content = b'hello world'
    client.post(f'/upload/{item}', files={'file': ('note.txt', content, 'text/plain')})
    r = client.get(f'/view/{item}/note.txt')
    assert r.status_code == 200
    assert r.content == content
    assert 'attachment' not in r.headers.get('content-disposition', '')


def test_rename_attachment(client, item, data_dir):
    client.post(f'/upload/{item}', files={'file': ('old.txt', b'x', 'text/plain')})
    r = client.post(f'/rename-attachment/{item}/old.txt', data={'new_name': 'new.txt'})
    assert r.status_code == 200
    assert (data_dir / item / 'new.txt').exists()
    assert not (data_dir / item / 'old.txt').exists()


def test_rename_attachment_preserves_extension(client, item, data_dir):
    client.post(f'/upload/{item}', files={'file': ('doc.txt', b'x', 'text/plain')})
    r = client.post(f'/rename-attachment/{item}/doc.txt', data={'new_name': 'doc.pdf'})
    assert r.status_code == 200
    assert (data_dir / item / 'doc.pdf.txt').exists()
    assert not (data_dir / item / 'doc.pdf').exists()


def test_rename_attachment_allows_dot_in_stem(client, item, data_dir):
    client.post(f'/upload/{item}', files={'file': ('doc.txt', b'x', 'text/plain')})
    r = client.post(f'/rename-attachment/{item}/doc.txt', data={'new_name': 'my.backup'})
    assert r.status_code == 200
    assert (data_dir / item / 'my.backup.txt').exists()


def test_rename_attachment_dedupes_extension(client, item, data_dir):
    client.post(f'/upload/{item}', files={'file': ('doc.txt', b'x', 'text/plain')})
    r = client.post(f'/rename-attachment/{item}/doc.txt', data={'new_name': 'newname.txt'})
    assert r.status_code == 200
    assert (data_dir / item / 'newname.txt').exists()
    assert not (data_dir / item / 'newname.txt.txt').exists()


def test_rename_attachment_conflict(client, item, data_dir):
    for name in ('a.txt', 'b.txt'):
        client.post(f'/upload/{item}', files={'file': (name, b'x', 'text/plain')})
    r = client.post(f'/rename-attachment/{item}/a.txt', data={'new_name': 'b.txt'})
    assert r.status_code == 409
    assert (data_dir / item / 'a.txt').exists()


# --- Move ---

def test_move_item(client, data_dir):
    # Create two items then move one into the other
    for name in ('Container', 'Widget'):
        client.post('/new/', data={'name': name, 'content': '', 'label': 'no'},
                    files={'photo': ('', b'', 'application/octet-stream')})

    r = client.post('/move/Widget', data={'destination': 'Container', 'by_id': ''})
    assert r.status_code == 200
    assert (data_dir / 'Container' / 'Widget').is_dir()
    assert not (data_dir / 'Widget').exists()


# --- Add (session log form) ---

def test_add_form(client):
    r = client.get('/new/')
    assert r.status_code == 200


def test_add_item(client, data_dir):
    r = client.post('/new/', data={'name': 'Bulk Box', 'content': '', 'label': 'no'},
                    files={'photo': ('', b'', 'application/octet-stream')})
    assert r.status_code == 200
    assert (data_dir / 'Bulk Box' / 'index.md').exists()
    assert 'added=Bulk+Box' in str(r.url) or 'added=Bulk%20Box' in str(r.url)


def test_add_with_photo(client, data_dir):
    r = client.post('/new/', data={'name': 'Photo Box', 'content': '', 'label': 'no'},
                    files={'photo': ('photo.jpg', b'\xff\xd8\xff', 'image/jpeg')})
    assert r.status_code == 200
    assert (data_dir / 'Photo Box' / 'photo.jpg').exists()


def test_add_with_content(client, data_dir):
    r = client.post('/new/', data={'name': 'Described Box', 'content': 'some notes', 'label': 'no'},
                    files={'photo': ('', b'', 'application/octet-stream')})
    assert r.status_code == 200
    index = (data_dir / 'Described Box' / 'index.md').read_text()
    assert 'some notes' in index


def test_add_conflict(client, data_dir):
    client.post('/new/', data={'name': 'Clash', 'content': '', 'label': 'no'},
                files={'photo': ('', b'', 'application/octet-stream')})
    r = client.post('/new/', data={'name': 'Clash', 'content': '', 'label': 'no'},
                    files={'photo': ('', b'', 'application/octet-stream')})
    assert r.status_code == 409


def test_add_missing_parent(client):
    r = client.get('/new/nonexistent-location')
    assert r.status_code == 404
