// Generic autocomplete for text inputs. Works on desktop and mobile.
//
// autocomplete(input, getOptions)
//   input      — the <input> element to attach to
//   getOptions — function(currentValue) → string[] of suggestions
//
// The dropdown is appended to <body> and positioned with getBoundingClientRect
// so it floats above all content regardless of ancestors' overflow/position.

function autocomplete(input, getOptions) {
    input.addEventListener('input', () => _acShow(input, getOptions));
    input.addEventListener('focus', () => _acShow(input, getOptions));
}

let _acTarget = null;

function _acShow(input, getOptions) {
    _acDismiss();
    const items = getOptions(input.value);
    if (!items.length) return;

    const rect = input.getBoundingClientRect();
    const bg   = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#fff';
    const ul   = document.createElement('ul');
    ul.className = 'autocomplete-list';
    ul.style.cssText =
        'position:fixed;top:' + rect.bottom + 'px;left:' + rect.left +
        'px;width:' + rect.width + 'px;z-index:9999;background:' + bg + ';';

    items.forEach(text => {
        const li = document.createElement('li');
        li.textContent = text;

        // Desktop: mousedown fires before blur, so we can prevent blur and set value.
        li.addEventListener('mousedown', e => {
            e.preventDefault();
            input.value = text;
            _acDismiss();
            input.dispatchEvent(new Event('ac-select', { bubbles: true }));
        });

        // Mobile: distinguish tap from scroll via touchmove.
        // touchmove also dismisses the list globally (see below), so by the time
        // touchend fires after a scroll the isTap flag is already false.
        let isTap = false;
        li.addEventListener('touchstart', () => { isTap = true;  }, { passive: true });
        li.addEventListener('touchmove',  () => { isTap = false; }, { passive: true });
        li.addEventListener('touchend', e => {
            if (!isTap) return;
            e.preventDefault(); // prevent synthetic mousedown/click double-fire
            input.value = text;
            _acDismiss();
            input.dispatchEvent(new Event('ac-select', { bubbles: true }));
        });

        ul.appendChild(li);
    });

    _acTarget = input;
    document.body.appendChild(ul);
}

function _acDismiss() {
    document.querySelectorAll('.autocomplete-list').forEach(el => el.remove());
    _acTarget = null;
}

document.addEventListener('click',  e  => { if (e.target !== _acTarget) _acDismiss(); });
document.addEventListener('scroll', _acDismiss, { passive: true, capture: true });

// ── Fields editor ─────────────────────────────────────────────────────────────

let _fields = {};
fetch('/api/fields').then(r => r.json()).then(data => { _fields = data; });

function _attachFieldRow(row) {
    const keyInput = row.querySelector('[name="field_key"]');
    const valInput = row.querySelector('[name="field_value"]');
    if (!keyInput || !valInput) return; // .field-row reused by non-field-editor forms
    autocomplete(keyInput, q => {
        const keys = Object.keys(_fields);
        return q ? keys.filter(k => k.toLowerCase().includes(q.toLowerCase())) : keys;
    });
    autocomplete(valInput, q => {
        const vals = _fields[keyInput.value] || [];
        return q ? vals.filter(v => v.toLowerCase().includes(q.toLowerCase())) : vals;
    });
    keyInput.addEventListener('ac-select', () => {
        valInput.focus();
        _acShow(valInput, () => _fields[keyInput.value] || []);
    });
}

function addField() {
    const row = document.createElement('div');
    row.className = 'field-row';
    row.innerHTML =
        '<input type="text" name="field_key" placeholder="key" aria-label="Field key">'
      + '<input type="text" name="field_value" placeholder="value" aria-label="Field value">'
      + '<button type="button" aria-label="Remove field" onclick="this.closest(\'.field-row\').remove()">✕</button>';
    document.getElementById('fields-container').appendChild(row);
    _attachFieldRow(row);
    row.querySelector('input').focus();
}

document.querySelectorAll('.field-row').forEach(_attachFieldRow);
