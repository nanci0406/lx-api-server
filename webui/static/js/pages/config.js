// 配置页：分组表单 + 原始配置(config.yml)编辑

import { h, icon, api, setChildren, toast, confirmDialog, switchControl, passwordInput, withLoading } from '../core.js';

const RAW = '__raw';
const ICONS = { server: 'server', shield: 'shield', code: 'code', music: 'music', folder: 'folder' };

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function parseNumber(text) {
  const trimmed = String(text).trim();
  if (trimmed !== '' && Number.isFinite(Number(trimmed))) return Number(trimmed);
  return text; // 交给服务端校验并给出错误提示
}

// ---------------------------------------------------------------------------
// 标签输入(列表类配置)
// ---------------------------------------------------------------------------

function tagInput(values, onChange, { numeric = false, placeholder = '' } = {}) {
  let items = values.map(String);
  const input = h('input', { placeholder: placeholder ? `${placeholder}，回车添加` : '输入后回车添加', inputmode: numeric ? 'numeric' : 'text',
    autocomplete: 'off', spellcheck: 'false' });
  const root = h('div', { class: 'tag-input' });
  root.addEventListener('click', (event) => { if (event.target === root) input.focus(); });

  const emit = () => onChange(numeric ? items.map((item) => (/^\d+$/.test(item) ? Number(item) : item)) : [...items]);
  const render = () => {
    root.replaceChildren(...items.map((item, index) => h('span', { class: 'tag' }, item,
      h('button', { type: 'button', 'aria-label': `删除 ${item}`, onclick: () => { items.splice(index, 1); render(); emit(); } }, icon('x')))), input);
  };
  const commit = () => {
    const parts = input.value.split(/[\s,，]+/).map((part) => part.trim()).filter(Boolean);
    if (!parts.length) return false;
    for (const part of parts) {
      if (numeric && !/^\d+$/.test(part)) { toast(`“${part}”不是有效的数字`, 'error'); continue; }
      if (!items.includes(part)) items.push(part);
    }
    input.value = '';
    render();
    emit();
    input.focus();
    return true;
  };
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ',' || event.key === '，') {
      event.preventDefault();
      commit();
    } else if (event.key === 'Backspace' && !input.value && items.length) {
      items.pop();
      render();
      emit();
    }
  });
  input.addEventListener('blur', commit);
  render();
  return root;
}

// ---------------------------------------------------------------------------
// 页面
// ---------------------------------------------------------------------------

export async function configPage(ctx) {
  let sections = [];
  let original = {};
  let draft = {};
  let errors = {};
  let restartNotice = [];
  let active = ctx.hash || 'service';
  const raw = { loaded: false, original: '', value: '' };
  const fieldEls = {};

  const rawDirty = () => raw.loaded && raw.value !== raw.original;
  ctx.setGuard(() => (Object.keys(draft).length || rawDirty()) ? '配置有未保存的修改，离开后这些修改会丢失。' : null);

  const head = h('div', { class: 'page-head' }, h('div', null, h('h2', null, '配置'),
    h('p', null, '修改后点击底部的「保存并生效」，大部分配置立即生效；标有「需重启」的项目要重启服务后才会生效。')));
  const tabs = h('nav', { class: 'config-tabs', 'aria-label': '配置分组' });
  const panel = h('div', { class: 'config-panel' });
  const barText = h('span', { class: 'text' });
  const saveButton = h('button', { class: 'btn primary sm', type: 'button' }, icon('check'), '保存并生效');
  const discardButton = h('button', { class: 'btn ghost sm', type: 'button' }, '放弃修改');
  const saveBar = h('div', { class: 'save-bar', role: 'region', 'aria-label': '保存修改' }, barText, discardButton, saveButton);
  setChildren(ctx.container, head,
    h('div', { class: 'config-layout' }, tabs, panel),
    saveBar);
  setChildren(panel, h('div', { class: 'card' }, h('div', { class: 'card-body stack' },
    h('div', { class: 'skeleton title' }), h('div', { class: 'skeleton line' }), h('div', { class: 'skeleton block' }))));

  const load = async () => {
    const data = await api('GET', '/api/admin/config');
    sections = data.sections;
    original = {};
    for (const section of sections) for (const f of section.fields) original[f.key] = f.value;
    draft = {};
    errors = {};
  };

  const valueOf = (key) => (key in draft ? draft[key] : original[key]);
  const sectionOf = (key) => sections.find((section) => section.fields.some((f) => f.key === key));

  const setValue = (key, value) => {
    if (same(value, original[key])) delete draft[key];
    else draft[key] = value;
    delete errors[key];
    markField(key);
  };

  // 撤销某一项的修改(密钥类字段的"没有修改"无法用值比较表示，所以单独处理)
  const clearDraft = (key) => {
    delete draft[key];
    delete errors[key];
    markField(key);
  };

  const markField = (key) => {
    const el = fieldEls[key];
    if (el) {
      el.classList.toggle('dirty', key in draft);
      el.classList.remove('has-error');
      const errorEl = el.querySelector('.field-error');
      if (errorEl) errorEl.remove();
    }
    updateDepends();
    updateBar();
    renderTabs();
  };

  function updateBar() {
    const count = Object.keys(draft).length;
    barText.textContent = count ? `${count} 项修改未保存` : '';
    saveBar.classList.toggle('show', count > 0);
  }

  // ---------- 分组标签 ----------

  function renderTabs() {
    const items = sections.map((section) => {
      const changed = section.fields.filter((f) => f.key in draft).length;
      const failed = section.fields.filter((f) => f.key in errors).length;
      return h('button', { type: 'button', class: ['config-tab', active === section.id && 'on'], onclick: () => switchTab(section.id) },
        icon(ICONS[section.icon] || 'sliders'), section.title,
        failed ? h('span', { class: 'count err' }, failed) : (changed ? h('span', { class: 'count' }, changed) : null));
    });
    items.push(h('button', { type: 'button', class: ['config-tab', active === RAW && 'on'], onclick: () => switchTab(RAW) },
      icon('file'), '原始配置', rawDirty() ? h('span', { class: 'count' }, '•') : null));
    tabs.replaceChildren(...items);
  }

  async function switchTab(id) {
    if (id === active) return;
    if (id === RAW && Object.keys(draft).length) {
      toast('请先保存或放弃表单里的修改，再编辑原始配置', 'warn');
      return;
    }
    if (active === RAW && rawDirty()) {
      const okLeave = await confirmDialog({ title: '放弃原始配置的修改？', message: '原始配置有未保存的修改，切换后这些修改会丢失。',
        confirmText: '放弃修改', danger: true });
      if (!okLeave) return;
      raw.value = raw.original;
    }
    active = id;
    history.replaceState(null, '', `${location.pathname}${location.search}#${id}`);
    renderTabs();
    renderPanel();
    if (window.innerWidth <= 960) window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ---------- 字段 ----------

  function labelRow(f) {
    return h('label', { class: 'field-label', for: `cfg-${f.key}` }, f.label,
      f.restart ? h('span', { class: 'restart-tag', title: '修改后需要重启服务才会生效' }, '需重启') : null);
  }

  // 每一项配置是一行：左边是名称和说明，右边是控件；列表、多行文本等宽控件放到说明下方。
  // 从属项(depends)缩进显示，所依赖的开关关闭时变灰并提示，但仍然可以修改。
  function wrapField(f, control, { kind = 'inline' } = {}) {
    const error = errors[f.key];
    const parent = f.depends ? fieldByKey(f.depends) : null;
    const el = h('div', { class: ['setting', kind, f.depends && 'sub', f.key in draft && 'dirty', error && 'has-error'] },
      h('div', { class: 'setting-text' }, labelRow(f),
        f.help ? h('div', { class: 'field-help' }, f.help) : null,
        parent ? h('div', { class: 'dep-hint' }, icon('info'), `开启「${parent.label}」后生效`) : null,
        error ? h('div', { class: 'field-error' }, error) : null),
      h('div', { class: 'setting-control' }, control));
    fieldEls[f.key] = el;
    return el;
  }

  const fieldByKey = (key) => {
    for (const section of sections) {
      const found = section.fields.find((f) => f.key === key);
      if (found) return found;
    }
    return null;
  };

  // 依赖链上任意一个开关关闭，这一项就不生效
  const isActive = (f) => {
    const seen = new Set();
    let current = f;
    while (current && current.depends && !seen.has(current.key)) {
      seen.add(current.key);
      if (!valueOf(current.depends)) return false;
      current = fieldByKey(current.depends);
    }
    return true;
  };

  function updateDepends() {
    for (const [key, el] of Object.entries(fieldEls)) {
      const f = fieldByKey(key);
      if (f && f.depends) el.classList.toggle('off', !isActive(f));
    }
  }

  function secretControl(f) {
    const info = original[f.key] || { set: false, preview: '' };
    const box = h('div', { class: 'secret-control' });
    let editing = false;
    const render = () => {
      const pending = f.key in draft;
      if (pending && draft[f.key] === '') {
        box.replaceChildren(h('div', { class: 'secret-box' },
          h('div', { class: 'state unset' }, icon('trash'), '保存后将清空'),
          h('button', { type: 'button', class: 'btn ghost sm', onclick: () => { clearDraft(f.key); render(); } }, '撤销')));
        return;
      }
      if (editing || pending) {
        const props = { id: `cfg-${f.key}`, placeholder: info.set ? '输入新的值(留空则不修改)' : '输入值', value: pending ? draft[f.key] : '' };
        let control;
        let input;
        if (f.multiline) {
          input = h('textarea', Object.assign({ class: 'textarea code', rows: 4, spellcheck: 'false' }, props));
          control = input;
        } else {
          control = passwordInput(props);
          input = control.input;
        }
        input.addEventListener('input', () => {
          if (input.value) setValue(f.key, input.value); else clearDraft(f.key);
        });
        box.replaceChildren(h('div', { class: 'stack tight' }, control,
          h('div', { class: 'row' }, h('button', { type: 'button', class: 'btn ghost sm', onclick: () => { editing = false; clearDraft(f.key); render(); } },
            '取消修改'))));
        setTimeout(() => input.focus(), 30);
        return;
      }
      box.replaceChildren(h('div', { class: 'secret-box' },
        h('div', { class: ['state', !info.set && 'unset'] }, icon(info.set ? 'lock' : 'info'),
          info.set ? (info.preview ? `已设置 · 末尾 ${info.preview}` : '已设置') : '未设置'),
        h('button', { type: 'button', class: 'btn soft sm', onclick: () => { editing = true; render(); } }, info.set ? '修改' : '设置'),
        info.set ? h('button', { type: 'button', class: 'btn ghost sm', onclick: () => { setValue(f.key, ''); render(); } }, '清空') : null));
    };
    render();
    return box;
  }

  function renderField(f) {
    const value = valueOf(f.key);
    const id = `cfg-${f.key}`;
    switch (f.type) {
      case 'bool': {
        const control = switchControl({ checked: Boolean(value), onChange: (checked) => setValue(f.key, checked) });
        control.querySelector('input').id = id;
        return wrapField(f, control, { kind: 'toggle' });
      }
      case 'int':
      case 'number': {
        const input = h('input', { id, class: 'input', inputmode: f.type === 'int' ? 'numeric' : 'decimal', value: String(value ?? ''),
          placeholder: f.placeholder || '' });
        input.addEventListener('input', () => setValue(f.key, parseNumber(input.value)));
        const control = f.unit ? h('div', { class: 'input-affix' }, input, h('span', { class: 'affix' }, f.unit)) : input;
        return wrapField(f, control);
      }
      case 'select': {
        const select = h('select', { id, class: 'select' },
          f.options.map(([optionValue, label]) => h('option', { value: optionValue, selected: optionValue === value }, label)));
        select.value = value;
        select.addEventListener('change', () => setValue(f.key, select.value));
        return wrapField(f, select);
      }
      case 'textarea': {
        const area = h('textarea', { id, class: 'textarea', rows: 3, value: value ?? '' });
        area.addEventListener('input', () => setValue(f.key, area.value));
        return wrapField(f, area, { kind: 'wide' });
      }
      case 'list':
      case 'int_list':
        return wrapField(f, tagInput(value || [], (items) => setValue(f.key, items),
          { numeric: f.type === 'int_list', placeholder: f.placeholder }), { kind: 'wide' });
      case 'multi': {
        let chosen = new Set(value || []);
        const chips = h('div', { class: 'chips' });
        const render = () => chips.replaceChildren(...f.options.map((option) => {
          const on = chosen.has(option);
          return h('button', { type: 'button', class: ['chip', on && 'on'], 'aria-pressed': on ? 'true' : 'false',
            onclick: () => {
              if (on) chosen.delete(option); else chosen.add(option);
              setValue(f.key, f.options.filter((o) => chosen.has(o)));
              render();
            } }, on ? icon('check') : null, option);
        }));
        render();
        return wrapField(f, chips, { kind: 'wide' });
      }
      case 'secret':
        return wrapField(f, secretControl(f), { kind: f.multiline ? 'wide' : 'inline' });
      default: {
        const input = h('input', { id, class: 'input', value: value ?? '', placeholder: f.placeholder || '', spellcheck: 'false' });
        input.addEventListener('input', () => setValue(f.key, input.value));
        return wrapField(f, input);
      }
    }
  }

  // ---------- 面板 ----------

  function renderPanel() {
    if (active === RAW) { renderRaw(); return; }
    let section = sections.find((s) => s.id === active);
    if (!section) { section = sections[0]; active = section.id; renderTabs(); }
    for (const key of Object.keys(fieldEls)) delete fieldEls[key];
    const notices = [];
    if (restartNotice.length) {
      notices.push(h('div', { class: 'notice warn' }, icon('alert'),
        h('div', null, '已保存。以下修改需要重启服务后才会生效：', h('b', null, restartNotice.join('、')))));
    }
    const fields = h('div', { class: 'setting-list stagger' }, section.fields.map(renderField));
    Array.from(fields.children).forEach((child, index) => child.style.setProperty('--i', String(Math.min(index, 12))));
    updateDepends();
    panel.replaceChildren(h('section', { class: 'card page-enter' },
      h('div', { class: 'card-header' }, h('div', { class: 'card-icon' }, icon(ICONS[section.icon] || 'sliders')),
        h('div', { class: 'grow' }, h('h3', { class: 'card-title' }, section.title), h('p', { class: 'card-sub' }, section.description))),
      notices.length ? h('div', { class: 'card-body' }, notices) : null,
      fields));
  }

  function renderRaw() {
    const area = h('textarea', { class: 'textarea code raw-editor', spellcheck: 'false', rows: 26, 'aria-label': 'config.yml 内容' });
    const status = h('div', { class: 'raw-status' });
    const reloadButton = h('button', { class: 'btn', type: 'button' }, icon('refresh'), '重新加载');
    const saveRawButton = h('button', { class: 'btn primary', type: 'button' }, icon('check'), '保存原始配置');
    const updateStatus = () => {
      status.replaceChildren(rawDirty() ? h('span', { class: 'pill brand' }, h('span', { class: 'dot' }), '有未保存的修改') : null);
      renderTabs();
    };
    area.addEventListener('input', () => { raw.value = area.value; updateStatus(); });
    area.addEventListener('keydown', (event) => {
      if (event.key === 'Tab' && !event.shiftKey) {
        event.preventDefault();
        const { selectionStart, selectionEnd } = area;
        area.setRangeText('  ', selectionStart, selectionEnd, 'end');
        raw.value = area.value;
        updateStatus();
      }
    });
    const loadRaw = async () => {
      const data = await api('GET', '/api/admin/config/raw');
      raw.loaded = true;
      raw.original = raw.value = data.content;
      area.value = data.content;
      updateStatus();
    };
    reloadButton.addEventListener('click', () => withLoading(reloadButton, async () => {
      if (rawDirty() && !(await confirmDialog({ title: '重新加载？', message: '未保存的修改会丢失。', confirmText: '重新加载', danger: true }))) return;
      await loadRaw();
      toast('已重新加载配置文件', 'success', 2000);
    }));
    saveRawButton.addEventListener('click', () => withLoading(saveRawButton, async () => {
      if (!rawDirty()) { toast('没有需要保存的修改', 'info'); return; }
      const okSave = await confirmDialog({ title: '保存原始配置', confirmText: '保存并生效',
        message: '将直接覆盖 config.yml 并热重载配置。保存前会自动备份为 config/config.yml.bak；如果新配置无法加载，会自动恢复原配置。' });
      if (!okSave) return;
      try {
        const data = await api('PUT', '/api/admin/config/raw', { content: raw.value });
        raw.original = raw.value = data.content;
        area.value = data.content;
        updateStatus();
        await load();
        toast('原始配置已保存并生效', 'success');
      } catch (e) {
        toast(e.message, 'error', 9000);
      }
    }));
    panel.replaceChildren(h('section', { class: 'card page-enter' },
      h('div', { class: 'card-header' }, h('div', { class: 'card-icon' }, icon('file')),
        h('div', { class: 'grow' }, h('h3', { class: 'card-title' }, '原始配置 · config.yml'),
          h('p', { class: 'card-sub' }, '配置文件的全部内容，包括账号池(module.cookiepool)等表单里没有的配置')), status),
      h('div', { class: 'card-body stack' },
        h('div', { class: 'notice warn' }, icon('lock'), h('div', null, '这里会显示所有账号凭证的明文，请不要截图或分享。')),
        area,
        h('div', { class: 'row wrap' }, h('span', { class: 'faint' }, 'YAML 格式，缩进使用空格；按 Tab 插入两个空格'), h('span', { class: 'spacer' }),
          reloadButton, saveRawButton))));
    if (raw.loaded) { area.value = raw.value; updateStatus(); } else {
      area.value = '正在加载…';
      area.disabled = true;
      loadRaw().then(() => { area.disabled = false; }).catch((e) => { area.value = ''; toast(e.message, 'error'); });
    }
  }

  // ---------- 保存 ----------

  async function save() {
    if (!Object.keys(draft).length) return;
    try {
      const payload = await api('PUT', '/api/admin/config', { values: draft });
      sections = payload.sections;
      original = {};
      for (const section of sections) for (const f of section.fields) original[f.key] = f.value;
      draft = {};
      errors = {};
      restartNotice = payload.restart_required || [];
      updateBar();
      renderTabs();
      renderPanel();
      if (payload.reload_error) toast(`配置已保存，但热重载失败：${payload.reload_error}`, 'error', 9000);
      else toast(restartNotice.length ? '已保存，部分修改需要重启后生效' : '已保存并生效', restartNotice.length ? 'warn' : 'success');
    } catch (e) {
      if (e.status === 400 && e.data && e.data.errors) {
        errors = e.data.errors;
        const first = Object.keys(errors).map(sectionOf).find(Boolean);
        if (first) active = first.id;
        renderTabs();
        renderPanel();
      }
      toast(e.message, 'error');
    }
  }

  saveButton.addEventListener('click', () => withLoading(saveButton, save));
  discardButton.addEventListener('click', () => {
    draft = {};
    errors = {};
    updateBar();
    renderTabs();
    renderPanel();
    toast('已放弃修改', 'info', 1800);
  });
  const onKey = (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      if (Object.keys(draft).length) withLoading(saveButton, save);
    }
  };
  document.addEventListener('keydown', onKey);
  ctx.onCleanup(() => document.removeEventListener('keydown', onKey));

  await load();
  if (!ctx.alive()) return;
  if (active !== RAW && !sections.some((s) => s.id === active)) active = sections[0].id;
  renderTabs();
  renderPanel();
}
