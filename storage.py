import logging
import os
import yaml
import uuid
import base64
import markdown
import shutil
import re
from pathlib import Path
from fuzzywuzzy import fuzz
from fuzzywuzzy import process
from config import settings

log = logging.getLogger(__name__)

HOUSE_ROOT = Path(settings.data_dir)
HOUSE_ROOT.mkdir(exist_ok=True)

IGNORED_ATTACHMENTS = ['index.md', 'photo.jpg', 'thumbnail.jpg']
UUID_LENGTH = 8
SYSTEM_KEYS = frozenset({'id', 'name', 'path', 'content', 'html_content', 'photo_path'})

_FORBIDDEN_NAME_RE = re.compile(r'[/?#\x00-\x1f]')


def validate_item_name(name: str):
    """Raise ValueError if name contains characters that break URL routing or the filesystem."""
    if not name or name in ('.', '..'):
        raise ValueError("Name cannot be empty")
    if _FORBIDDEN_NAME_RE.search(name):
        raise ValueError("Name may not contain /, ?, or # (reserved URL/path characters)")

_hierarchy_cache: tuple | None = None


def _invalidate_hierarchy():
    global _hierarchy_cache
    _hierarchy_cache = None


def get_hierarchy():
    global _hierarchy_cache
    if _hierarchy_cache is None:
        _hierarchy_cache = build_item_hierarchy(HOUSE_ROOT)
    items, total, _ = _hierarchy_cache
    return items, total


def get_fields() -> dict[str, list]:
    global _hierarchy_cache
    if _hierarchy_cache is None:
        _hierarchy_cache = build_item_hierarchy(HOUSE_ROOT)
    _, _, fields = _hierarchy_cache
    return {k: sorted(v) for k, v in sorted(fields.items())}


def generate_id():
    while True:
        candidate = base64.urlsafe_b64encode(uuid.uuid4().bytes).decode('utf-8')[:UUID_LENGTH]
        if not find_item_by_id(candidate):
            return candidate


def shift_headings_down(markdown_text):
    def shift_heading(line):
        match = re.match(r'^(#{1,6})\s+(.*)', line)
        if match:
            new_level = min(6, len(match.group(1)) + 1)
            return '#' * new_level + ' ' + match.group(2)
        return line

    return '\n'.join(shift_heading(line) for line in markdown_text.splitlines())


def adjust_paths_in_markdown(md_content, base_dir):
    url_pattern = r'(!?\[.*?\]\((.*?)\))'

    def adjust_path(match):
        element = match.group(0)
        path = match.group(2)
        if not path.startswith('http') and not path.startswith('#'):
            return element.replace(path, os.path.join(base_dir, path))
        return element

    return re.sub(url_pattern, adjust_path, md_content)


def render_html(markdown_text, item_path):
    markdown_text = adjust_paths_in_markdown(markdown_text, '/download/' / item_path)
    markdown_text = shift_headings_down(markdown_text)
    return markdown.markdown(markdown_text)


def read_index_file(item_path):
    index_path = item_path / "index.md"
    if not index_path.exists():
        return None

    content = index_path.read_text()

    if content.startswith("---"):
        _, yaml_text, markdown_text = content.split("---", 2)
        metadata = yaml.safe_load(yaml_text)
        markdown_text = markdown_text.strip()
    else:
        metadata = {"name": item_path.name, "id": ""}
        markdown_text = content

    photo_path = None
    if os.path.isfile(item_path / 'photo.png'):
        photo_path = Path('/download/') / Path(*list(item_path.parts[1:])) / 'photo.png'
    elif os.path.isfile(item_path / 'photo.jpg'):
        photo_path = Path('/download/') / Path(*list(item_path.parts[1:])) / 'photo.jpg'

    return {
        **metadata,
        "name": item_path.name,
        "path": item_path.relative_to(HOUSE_ROOT),
        "content": markdown_text,
        "html_content": render_html(markdown_text, Path(*list(item_path.parts[1:]))),
        "photo_path": photo_path,
    }


def list_directory_items(directory_path):
    items = []
    attachments = []

    if not directory_path.exists():
        return items, attachments

    for path in directory_path.iterdir():
        if path.is_dir() and path.name != ".git":
            items.append(read_index_file(path))
        elif path.is_file() and path.name not in IGNORED_ATTACHMENTS:
            attachments.append({
                "name": path.name,
                "owner": os.path.basename(os.path.dirname(path)),
                "path": path.relative_to(HOUSE_ROOT),
                "parent_path": Path(os.path.dirname(path)).relative_to(HOUSE_ROOT),
                "size": path.stat().st_size,
            })

    items.sort(key=lambda x: x["name"].lower())
    attachments.sort(key=lambda x: x["name"].lower())
    return items, attachments


def list_all_items(directory_path):
    items, attachments = list_directory_items(directory_path)

    for path in directory_path.iterdir():
        if path.is_dir() and path.name != ".git":
            sub_items, sub_attachments = list_all_items(path)
            items.extend(sub_items)
            attachments.extend(sub_attachments)

    return items, attachments


def build_item_hierarchy(directory_path, total=0, fields=None):
    if fields is None:
        fields = {}
    items = []
    if not directory_path.exists():
        return items, total, fields
    for path in directory_path.iterdir():
        if path.is_dir() and path.name != ".git":
            try:
                metadata = read_index_file(path)
                total += 1
                for k, v in metadata.items():
                    if k not in SYSTEM_KEYS and v is not None:
                        fields.setdefault(k, set()).add(str(v))
                sub_items, total, _ = build_item_hierarchy(path, total, fields)
                items.append({
                    "path": path.relative_to(HOUSE_ROOT),
                    "name": metadata.get("name", path.name),
                    "id": metadata.get("id", ""),
                    "photo_path": metadata.get("photo_path", ""),
                    "sub_items": sub_items,
                })
            except Exception:
                log.warning("Could not read metadata for %s, using directory name", path)
                total += 1
                sub_items, total, _ = build_item_hierarchy(path, total, fields)
                items.append({
                    "path": path.relative_to(HOUSE_ROOT),
                    "name": path.name,
                    "id": "",
                    "sub_items": sub_items,
                })
        items = sorted(items, key=lambda x: x["name"])
    return items, total, fields


def write_item_index(item_path: Path, item_id: str, fields: dict, content: str):
    """Write index.md for an item."""
    (item_path / "index.md").write_text(
        f"---\n{yaml.dump({'id': item_id, **fields})}---\n{content}")


def create_item(parent: Path, name: str, content: str = "", fields: dict | None = None) -> tuple[str, Path]:
    """Create a new item directory and index.md. Returns (item_id, item_path).
    Raises ValueError for invalid names, FileExistsError if already exists."""
    validate_item_name(name)
    item_path = parent / name
    if item_path.exists():
        raise FileExistsError(f"'{name}' already exists here")
    item_path.mkdir(parents=True)
    item_id = generate_id()
    write_item_index(item_path, item_id, fields or {}, content)
    _invalidate_hierarchy()
    return item_id, item_path


def update_item(item_path: Path, name: str | None = None, content: str | None = None,
                fields: dict | None = None, replace_fields: bool = False) -> Path:
    """Update an item's index.md and optionally rename it. Returns the (possibly new) path.

    fields=None leaves existing custom fields untouched.
    replace_fields=False (default): merge patch — null values delete individual keys.
    replace_fields=True: treat fields as the complete desired state (used by HTML form).
    Raises FileExistsError on rename conflict.
    """
    metadata = read_index_file(item_path) or {}
    item_id = metadata.get("id") or generate_id()
    new_content = content if content is not None else metadata.get("content", "")

    if replace_fields:
        preserved = fields if fields is not None else {}
    else:
        preserved = {k: v for k, v in metadata.items() if k not in SYSTEM_KEYS}
        if fields is not None:
            for k, v in fields.items():
                if v is None:
                    preserved.pop(k, None)
                else:
                    preserved[k] = v

    write_item_index(item_path, item_id, preserved, new_content)

    new_path = item_path
    if name and name.strip() != item_path.name:
        new_name = name.strip()
        validate_item_name(new_name)
        dest = item_path.parent / new_name
        if dest.exists():
            raise FileExistsError(f"'{new_name}' already exists here")
        item_path.rename(dest)
        new_path = dest

    _invalidate_hierarchy()
    return new_path


def delete_item(item_path: Path):
    """Promote children to parent directory, then remove the item."""
    parent = item_path.parent
    children, _ = list_directory_items(item_path)
    for child in children:
        (HOUSE_ROOT / child['path']).rename(parent / child['name'])
    shutil.rmtree(item_path)
    _invalidate_hierarchy()


def move_item(item_path: Path, dest_path: Path) -> Path:
    """Move item into dest_path. Returns new item path."""
    new_path = dest_path / item_path.name
    item_path.rename(new_path)
    _invalidate_hierarchy()
    return new_path


def find_item_by_id(item_id: str):
    for path in [HOUSE_ROOT] + list(HOUSE_ROOT.rglob('*')):
        if path.is_dir():
            try:
                metadata = read_index_file(path)
                if metadata and metadata.get("id") == item_id:
                    return path
            except Exception:
                log.debug("Skipping unreadable directory %s during ID search", path)
                continue
    return None


def fuzzy_search(query, items, attachments):
    results = {}

    item_names = [item["name"] for item in items]
    item_matches = process.extract(query, item_names, limit=5, scorer=fuzz.partial_ratio)

    for match in item_matches:
        matched_item = next(item for item in items if item["name"] == match[0])
        if matched_item["name"] not in results:
            results[matched_item['name']] = {
                "type": "item",
                "name": matched_item["name"],
                "path": matched_item["path"],
                "score": match[1],
            }

    for item in items:
        metadata = read_index_file(HOUSE_ROOT / item["path"])
        field_text = " ".join(str(v) for k, v in metadata.items() if k not in SYSTEM_KEYS and v)
        content_score = fuzz.partial_ratio(query, metadata["content"] + " " + field_text)
        if content_score > 50 and item["name"] not in results:
            results[item["name"]] = {
                "type": "item_content",
                "name": item["name"],
                "path": item["path"],
                "score": content_score,
            }
        elif content_score > 50 and results[item['name']]['score'] < content_score:
            results[item['name']]['score'] = content_score

    attachment_names = [a["name"] for a in attachments]
    attachment_matches = process.extract(query, attachment_names, limit=5, scorer=fuzz.partial_ratio)

    for match in attachment_matches:
        matched = next(a for a in attachments if a["name"] == match[0])
        if match[1] > 5 and matched['owner'] not in results:
            results[matched['owner']] = {
                "type": "attachment",
                "name": matched["owner"],
                "path": matched["parent_path"],
                "score": match[1],
            }
        elif match[1] > 5 and results[matched['owner']]['score'] < match[1]:
            results[matched['owner']]['score'] = match[1]

    return sorted(results.items(), key=lambda k: k[1]['score'], reverse=True)
