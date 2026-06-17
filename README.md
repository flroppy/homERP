# homERP

This is a home ERP system for tracking storage of evergreen items in the household. Purpose is to give every item a place so every item can be in it's place.

## Goals
These should always be thought about when implementing something
* Reduce friction as much as possible
  * No one will use it if it's hard to use
* Allow for maximum flexibility
  * Items and things are all shapes and sizes and will have different needs for what we want to save about them
  * This manifests by keeping "item" very general
  * The only required data is folder name and id
  * *Any* data can be stored about an item, manifested by arbitrary attachments
* Portable
  * All data stored should be extremely portable
  * This is currently implemented by having everything stored as a raw folder/file on the file system that can easily be manipulated by the user or backed up

## Parts

Every part is a folder with metadata (files) and other parts (folder) rendered with index.md for metadata
The index.md is rendered on the parts page and may have any information desired in it for reference.

## ID

ID is a base 64, 8 character long code. This allows for `281474976710656` unique items.

Since folders names are just the non-unique name this means there could be conflicts.

## Photo

All items *may* have a `photo.jpg` that will be used for thumbnails and will display on the item page. This should be used to allow for faster navigation as well as reminding you wtf "screws" means 5 years from now

## Attachments

Items may have an arbitrary amount of attachments that will be available for download on the items page.

# Random Notes I took for possible improvements

Consider having a "value" rating to allow sorting out low value items. A loose volume/size could be useful as a value/m^3 metric

Ideas for automation:

- AI image to name/description
- could also get idea of size from photo
- AI recommendation for storage ldeleted
- Show use random items and ask if they spark joy
- somehow suggest items to be deleted

Setup workflow:

* Go to item to create in to with label, browsing, or search
* Click create item and enter:
  * item name
  * optional description
  * optional photo
* Save/print label and provide options for where to land after

Could backup to git (allow easy changes by user externally) dulwich

Write a script to bulk edit grocy

## Name Ideas
* Binli?
* Mintri?
* Try to work a TLD in: .store, .house, .storage, .haus

## TODOs

### Features
- **Rename the project** — "homERP" is a placeholder; see Name Ideas below
- **User-defined tags / key-value pairs** — allow arbitrary metadata on items beyond just `id`; useful for aggregating info (e.g. value, size, category)
- **Git auto-backup** — `dulwich` is already imported and constants (`SSH_URL`, `GIT_AUTHOR`) are defined; `proposal.md` has a full implementation plan ready to go
- **Duplicate name check** — creating an item with an existing sibling name silently overwrites it; should return an error or prompt the user
- **Display attachments in browser** — for supported types (PDF, images, text), offer an inline view rather than always forcing a download
- **Rename attachments** — currently attachments can only be deleted; allow renaming them in the UI

### Bugs
- **Trailing spaces in name are broken** — item names with trailing spaces cause issues; should be stripped on save/create
- **Content field requires at least a space** — submitting an empty content field fails; should accept truly empty content
- **Thumbnail only handles `.jpg`** — the `/thumbnail` endpoint hardcodes `photo.jpg`, but `read_index_file` checks for both `photo.png` and `photo.jpg`; they should be consistent
- **Dead code in `move_item`** (`main.py` ~line 937) — unreachable printer backend code sits after a `return` statement; leftover from an old implementation

### Code Quality
- **Extract `build_item_hierarchy`** (`main.py:298`) — currently defined inline inside the `/all-items` route handler; should be a top-level helper
- **Remove debug `print()` calls** in `send_to_printer` — `'starting send_to_printer'`, `'Getting backend'`, `'Sending to printer'`, `'barcode send!'` should be removed or replaced with proper logging
- **CSS technical debt** — styles are written inline on HTML elements throughout templates; should be moved to a stylesheet
