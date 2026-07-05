// Generic autocomplete for text inputs. Works on desktop and mobile.
//
// autocomplete(input, getOptions)
//   input      — the <input> element to attach to
//   getOptions — function(currentValue) → string[] of suggestions
//
// Renders a .autocomplete-list <ul> positioned inside the nearest .ac-wrap
// ancestor. Dismisses on outside click/touch.

function autocomplete(input, getOptions) {
    input.addEventListener('input',  () => _acShow(input, getOptions));
    input.addEventListener('focus',  () => _acShow(input, getOptions));
}

function _acShow(input, getOptions) {
    _acDismiss();
    const items = getOptions(input.value);
    if (!items.length) return;
    const wrap = input.closest('.ac-wrap');
    if (!wrap) return;
    const ul = document.createElement('ul');
    ul.className = 'autocomplete-list';
    items.forEach(text => {
        const li = document.createElement('li');
        li.textContent = text;
        const select = e => {
            e.preventDefault();
            input.value = text;
            _acDismiss();
            input.dispatchEvent(new Event('ac-select', { bubbles: true }));
        };
        li.addEventListener('mousedown', select);
        li.addEventListener('touchend',  select);
        ul.appendChild(li);
    });
    wrap.appendChild(ul);
}

function _acDismiss() {
    document.querySelectorAll('.autocomplete-list').forEach(el => el.remove());
}

document.addEventListener('click', e => {
    if (!e.target.closest('.ac-wrap')) _acDismiss();
});

// ── Fields editor ─────────────────────────────────────────────────────────────

let _fields = {};
fetch('/api/fields').then(r => r.json()).then(data => { _fields = data; });

function _attachFieldRow(row) {
    const keyInput = row.querySelector('[name="field_key"]');
    const valInput = row.querySelector('[name="field_value"]');
    autocomplete(keyInput, q => {
        const keys = Object.keys(_fields);
        return q ? keys.filter(k => k.toLowerCase().includes(q.toLowerCase())) : keys;
    });
    autocomplete(valInput, q => {
        const vals = _fields[keyInput.value] || [];
        return q ? vals.filter(v => v.toLowerCase().includes(q.toLowerCase())) : vals;
    });
    // After picking a key, open value suggestions automatically
    keyInput.addEventListener('ac-select', () => {
        valInput.focus();
        _acShow(valInput, q => _fields[keyInput.value] || []);
    });
}

function addField() {
    const row = document.createElement('div');
    row.className = 'field-row';
    row.innerHTML =
        '<div class="ac-wrap"><input type="text" name="field_key" placeholder="key" aria-label="Field key"></div>'
      + '<div class="ac-wrap"><input type="text" name="field_value" placeholder="value" aria-label="Field value"></div>'
      + '<button type="button" aria-label="Remove field" onclick="this.closest(\'.field-row\').remove()">✕</button>';
    document.getElementById('fields-container').appendChild(row);
    _attachFieldRow(row);
    row.querySelector('input').focus();
}

// Attach autocomplete to any pre-populated rows (edit form)
document.querySelectorAll('.field-row').forEach(_attachFieldRow);
