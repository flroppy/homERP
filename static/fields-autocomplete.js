// Custom autocomplete for field key/value inputs. Works on mobile.
// Requires .ac-wrap wrappers around inputs and #fields-container in the form.

let _fields = {};

fetch('/api/fields').then(r => r.json()).then(data => { _fields = data; });

function _showAcList(input, items) {
    _dismissAcList();
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
            _dismissAcList();
            if (input.name === 'field_key') {
                const valInput = input.closest('.field-row').querySelector('[name="field_value"]');
                if (valInput) { valInput.focus(); onValueFocus(valInput); }
            }
        };
        li.addEventListener('mousedown', select);
        li.addEventListener('touchend', select);
        ul.appendChild(li);
    });
    wrap.appendChild(ul);
}

function _dismissAcList() {
    document.querySelectorAll('.autocomplete-list').forEach(el => el.remove());
}

function onKeyInput(input) {
    const q = input.value.toLowerCase();
    const keys = Object.keys(_fields).filter(k => !q || k.toLowerCase().includes(q));
    _showAcList(input, keys);
}

function onValueInput(input) {
    const key = input.closest('.field-row').querySelector('[name="field_key"]').value;
    const q = input.value.toLowerCase();
    const vals = (_fields[key] || []).filter(v => !q || v.toLowerCase().includes(q));
    _showAcList(input, vals);
}

function onValueFocus(input) {
    const key = input.closest('.field-row').querySelector('[name="field_key"]').value;
    _showAcList(input, _fields[key] || []);
}

function addField() {
    const row = document.createElement('div');
    row.className = 'field-row';
    row.innerHTML =
        '<div class="ac-wrap"><input type="text" name="field_key" placeholder="key" aria-label="Field key" oninput="onKeyInput(this)" onfocus="onKeyInput(this)"></div>'
      + '<div class="ac-wrap"><input type="text" name="field_value" placeholder="value" aria-label="Field value" oninput="onValueInput(this)" onfocus="onValueFocus(this)"></div>'
      + '<button type="button" aria-label="Remove field" onclick="this.closest(\'.field-row\').remove()">✕</button>';
    document.getElementById('fields-container').appendChild(row);
    row.querySelector('input').focus();
}

document.addEventListener('click', e => {
    if (!e.target.closest('.ac-wrap')) _dismissAcList();
});
