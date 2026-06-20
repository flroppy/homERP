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

HOUSE_ROOT = Path(settings.data_dir)
HOUSE_ROOT.mkdir(exist_ok=True)

IGNORED_ATTACHMENTS = ['index.md', 'photo.jpg', 'thumbnail.jpg']
UUID_LENGTH = 8

_hierarchy_cache: tuple | None = None


def _invalidate_hierarchy():
    global _hierarchy_cache
    _hierarchy_cache = None


def get_hierarchy():
    global _hierarchy_cache
    if _hierarchy_cache is None:
        _hierarchy_cache = build_item_hierarchy(HOUSE_ROOT)
    return _hierarchy_cache


def generate_id():
    random_id = uuid.uuid4().bytes
    return base64.urlsafe_b64encode(random_id).decode('utf-8')[:UUID_LENGTH]


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


def build_item_hierarchy(directory_path, total=0):
    items = []
    if not directory_path.exists():
        return items, total
    for path in directory_path.iterdir():
        if path.is_dir() and path.name != ".git":
            try:
                metadata = read_index_file(path)
                total += 1
                sub_items, total = build_item_hierarchy(path, total)
                items.append({
                    "path": path.relative_to(HOUSE_ROOT),
                    "name": metadata.get("name", path.name),
                    "id": metadata.get("id", ""),
                    "photo_path": metadata.get("photo_path", ""),
                    "sub_items": sub_items,
                })
            except Exception:
                total += 1
                sub_items, total = build_item_hierarchy(path, total)
                items.append({
                    "path": path.relative_to(HOUSE_ROOT),
                    "name": path.name,
                    "id": "",
                    "sub_items": sub_items,
                })
        items = sorted(items, key=lambda x: x["name"])
    return items, total


def find_item_by_id(item_id: str):
    for path in [HOUSE_ROOT] + list(HOUSE_ROOT.rglob('*')):
        if path.is_dir():
            try:
                metadata = read_index_file(path)
                if metadata and metadata.get("id") == item_id:
                    return path
            except Exception:
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
        content_score = fuzz.partial_ratio(query, metadata["content"])
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
