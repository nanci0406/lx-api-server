// LX API Server · 前端公共模块：DOM 构建、图标、接口请求、提示、对话框、格式化

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------

const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * 创建元素。文本一律作为文本节点插入，不使用 innerHTML，避免 XSS。
 * h('button', {class: 'btn', onclick: fn, disabled: true}, '保存')
 */
export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') el.className = Array.isArray(value) ? value.filter(Boolean).join(' ') : value;
      else if (key === 'style' && typeof value === 'object') Object.assign(el.style, value);
      else if (key === 'dataset') Object.assign(el.dataset, value);
      else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
      else if (key === 'value') el.value = value;
      else if (key === 'checked') el.checked = Boolean(value);
      else if (key === 'ref') value(el);
      else if (value === true) el.setAttribute(key, '');
      else el.setAttribute(key, String(value));
    }
  }
  append(el, children);
  return el;
}

export function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === true) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return parent;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function setChildren(el, ...children) {
  clear(el);
  return append(el, children);
}

/** 给容器的直接子元素设置依次出现的动画序号 */
export function stagger(el) {
  el.classList.add('stagger');
  Array.from(el.children).forEach((child, index) => child.style.setProperty('--i', String(index)));
  return el;
}

// ---------------------------------------------------------------------------
// 图标(24×24，线条风格)
// ---------------------------------------------------------------------------

const ICONS = {
  home: [['path', 'M3.5 10.5 12 3.5l8.5 7V20a1 1 0 0 1-1 1h-4.5v-6h-6v6H4.5a1 1 0 0 1-1-1z']],
  sliders: [['path', 'M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1'], ['circle', 15, 6, 2], ['circle', 9, 12, 2],
    ['circle', 17, 18, 2]],
  users: [['circle', 9, 8, 3.5], ['path', 'M2.5 20c.8-3.6 3.3-5.5 6.5-5.5s5.7 1.9 6.5 5.5'], ['circle', 17, 9, 2.5],
    ['path', 'M16.6 14.6c2.3.3 4 1.9 4.9 4.9']],
  user: [['circle', 12, 8, 4], ['path', 'M4 21c1.2-4 4.4-6 8-6s6.8 2 8 6']],
  chart: [['path', 'M3 20h18M6 20v-6M11 20V8M16 20v-9M21 20V4']],
  pulse: [['path', 'M3 12h4l3-8 4 16 3-8h4']],
  qr: [['rect', 4, 4, 6, 6, 1], ['rect', 14, 4, 6, 6, 1], ['rect', 4, 14, 6, 6, 1],
    ['path', 'M14 14h2v2h-2zM18 18h2v2h-2zM14 18h2M18 14h2']],
  shield: [['path', 'M12 3 4.5 6v6c0 4.4 3.2 7.9 7.5 9 4.3-1.1 7.5-4.6 7.5-9V6z'], ['path', 'M9 12l2 2 4-4']],
  key: [['circle', 8, 15, 4], ['path', 'M11 12l9-9M16 7l3 3M14 9l2 2']],
  lock: [['rect', 4.5, 11, 15, 10, 2], ['path', 'M8 11V7.5a4 4 0 0 1 8 0V11']],
  logout: [['path', 'M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 16l-4-4 4-4M6 12h10']],
  menu: [['path', 'M4 7h16M4 12h16M4 17h16']],
  x: [['path', 'M6 6l12 12M18 6 6 18']],
  refresh: [['path', 'M20 11a8 8 0 1 0-2.4 5.7M20 4.5V11h-6.5']],
  copy: [['rect', 9, 9, 11, 11, 2], ['path', 'M5 15V6a2 2 0 0 1 2-2h8']],
  eye: [['path', 'M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z'], ['circle', 12, 12, 3]],
  eyeOff: [['path', 'M2.5 12S6 5.5 12 5.5c1.6 0 3 .4 4.3 1M21.5 12s-3.5 6.5-9.5 6.5c-1.6 0-3-.4-4.3-1'],
    ['path', 'M4 4l16 16'], ['path', 'M9.9 9.9a3 3 0 0 0 4.2 4.2']],
  trash: [['path', 'M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13M10 11v5.5M14 11v5.5']],
  plus: [['path', 'M12 5v14M5 12h14']],
  check: [['path', 'M5 12.5l4.5 4.5L19 7']],
  alert: [['path', 'M12 3.5 2.5 20h19z'], ['path', 'M12 10v4.5M12 17.5v.01']],
  info: [['circle', 12, 12, 9], ['path', 'M12 11v6M12 7.5v.01']],
  checkCircle: [['circle', 12, 12, 9], ['path', 'M8 12.5l3 3 5-6']],
  xCircle: [['circle', 12, 12, 9], ['path', 'M9 9l6 6M15 9l-6 6']],
  sun: [['circle', 12, 12, 4], ['path', 'M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4']],
  moon: [['path', 'M20 14.5A8 8 0 0 1 9.5 4a7.5 7.5 0 1 0 10.5 10.5z']],
  monitor: [['rect', 3, 4, 18, 12, 2], ['path', 'M8 20h8M12 16v4']],
  music: [['path', 'M9 18V5.5l11-2V16'], ['circle', 6, 18, 3], ['circle', 17, 16, 3]],
  server: [['rect', 3, 4, 18, 7, 2], ['rect', 3, 13, 18, 7, 2], ['path', 'M7 7.5h.01M7 16.5h.01']],
  code: [['path', 'M8.5 7 3.5 12l5 5M15.5 7l5 5-5 5']],
  folder: [['path', 'M3 7.5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z']],
  file: [['path', 'M6 3h8l4 4v14H6z'], ['path', 'M14 3v4h4M9 13h6M9 17h6']],
  link: [['path', 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1'], ['path', 'M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1']],
  download: [['path', 'M12 4v11M7 10.5l5 5 5-5M4.5 20h15']],
  external: [['path', 'M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5']],
  phone: [['rect', 7, 2.5, 10, 19, 2.5], ['path', 'M11 18h2']],
  chat: [['path', 'M20.5 12a8.5 8.5 0 0 1-12.3 7.6L3.5 21l1.4-4.6A8.5 8.5 0 1 1 20.5 12z']],
  clock: [['circle', 12, 12, 9], ['path', 'M12 7v5l3.2 2']],
  play: [['path', 'M8 5v14l11-7z']],
  zap: [['path', 'M13 2.5 4.5 14H11l-1 7.5L19.5 10H13z']],
  search: [['circle', 11, 11, 6.5], ['path', 'M20 20l-4.2-4.2']],
  more: [['circle', 5.5, 12, 1.3, 'fill'], ['circle', 12, 12, 1.3, 'fill'], ['circle', 18.5, 12, 1.3, 'fill']],
  arrowRight: [['path', 'M5 12h14M13 6l6 6-6 6']],
  rotate: [['path', 'M4 12a8 8 0 0 1 13.7-5.6L20 8.5M20 4v4.5h-4.5M20 12a8 8 0 0 1-13.7 5.6L4 15.5M4 20v-4.5h4.5']],
  sparkles: [['path', 'M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z'], ['path', 'M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z']],
  logo: [['path', 'M9.5 17.5V6.5l9-2v11'], ['circle', 7, 17.5, 2.6, 'fill'], ['circle', 16, 15.5, 2.6, 'fill']],
};

export function icon(name, extraClass) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', 'icon' + (extraClass ? ' ' + extraClass : ''));
  for (const spec of ICONS[name] || ICONS.info) {
    const [type, ...args] = spec;
    let node;
    if (type === 'path') {
      node = document.createElementNS(SVG_NS, 'path');
      node.setAttribute('d', args[0]);
    } else if (type === 'circle') {
      node = document.createElementNS(SVG_NS, 'circle');
      node.setAttribute('cx', args[0]);
      node.setAttribute('cy', args[1]);
      node.setAttribute('r', args[2]);
      if (args[3] === 'fill') { node.setAttribute('fill', 'currentColor'); node.setAttribute('stroke', 'none'); }
    } else if (type === 'rect') {
      node = document.createElementNS(SVG_NS, 'rect');
      node.setAttribute('x', args[0]);
      node.setAttribute('y', args[1]);
      node.setAttribute('width', args[2]);
      node.setAttribute('height', args[3]);
      if (args[4]) node.setAttribute('rx', args[4]);
    }
    svg.appendChild(node);
  }
  return svg;
}

export function svg(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value !== undefined && value !== null) el.setAttribute(key, String(value));
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

// ---------------------------------------------------------------------------
// 接口请求
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(status, message, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

let unauthorizedHandler = null;
export function onUnauthorized(handler) { unauthorizedHandler = handler; }

export async function api(method, path, body) {
  const options = { method, credentials: 'same-origin', headers: { Accept: 'application/json' } };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch (e) {
    throw new ApiError(0, '网络连接失败，请检查服务是否在运行');
  }
  let payload = null;
  try { payload = await response.json(); } catch (e) { payload = null; }
  if (!response.ok || !payload || payload.code !== 0) {
    const message = (payload && payload.msg) || (response.status === 429 ? '请求太频繁，请稍后再试' : `请求失败(HTTP ${response.status})`);
    const error = new ApiError(response.status, message, payload && payload.data);
    if (response.status === 401 && unauthorizedHandler && !path.endsWith('/login')) unauthorizedHandler(error);
    throw error;
  }
  return payload.data;
}

// ---------------------------------------------------------------------------
// 提示
// ---------------------------------------------------------------------------

let toastStack = null;
const TOAST_ICONS = { success: 'checkCircle', error: 'xCircle', warn: 'alert', info: 'info' };

export function toast(message, type = 'info', timeout) {
  if (!toastStack) {
    toastStack = h('div', { class: 'toast-stack', role: 'status', 'aria-live': 'polite' });
    document.body.appendChild(toastStack);
  }
  const close = () => {
    if (!item.isConnected || item.classList.contains('out')) return;
    item.classList.add('out');
    item.addEventListener('animationend', () => item.remove(), { once: true });
    setTimeout(() => item.remove(), 400);
  };
  const item = h('div', { class: `toast ${type}` },
    icon(TOAST_ICONS[type] || 'info'),
    h('div', { class: 'toast-text' }, message),
    h('button', { class: 'icon-btn sm toast-close', 'aria-label': '关闭', onclick: close }, icon('x')));
  toastStack.appendChild(item);
  setTimeout(close, timeout || (type === 'error' ? 6000 : 3500));
  return close;
}

// ---------------------------------------------------------------------------
// 对话框
// ---------------------------------------------------------------------------

/**
 * 打开对话框。actions: [{label, kind, onClick}]，onClick 返回 false 时不关闭；返回 Promise 时按钮显示加载状态。
 */
export function modal({ title, body, actions = [], wide = false, onClose }) {
  const previousFocus = document.activeElement;
  let closed = false;
  const root = h('div', { class: 'modal-root' });
  const close = (result) => {
    if (closed) return;
    closed = true;
    document.removeEventListener('keydown', onKey);
    root.classList.add('closing');
    setTimeout(() => root.remove(), 220);
    if (previousFocus && previousFocus.focus) previousFocus.focus();
    if (onClose) onClose(result);
  };
  const onKey = (event) => { if (event.key === 'Escape') close(undefined); };
  const buttons = actions.map((action) => {
    const button = h('button', { class: `btn ${action.kind || ''}`, type: 'button' }, action.label);
    button.addEventListener('click', async () => {
      if (!action.onClick) { close(action.value); return; }
      button.disabled = true;
      button.classList.add('loading');
      try {
        const result = await action.onClick();
        if (result !== false) close(action.value);
      } finally {
        button.disabled = false;
        button.classList.remove('loading');
      }
    });
    return button;
  });
  const dialog = h('div', { class: ['modal', wide && 'wide'], role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
    h('div', { class: 'modal-head' }, h('h3', null, title), h('span', { class: 'spacer' }),
      h('button', { class: 'icon-btn', 'aria-label': '关闭', onclick: () => close(undefined) }, icon('x'))),
    h('div', { class: 'modal-body' }, body),
    buttons.length ? h('div', { class: 'modal-foot' }, buttons) : null);
  append(root, [h('div', { class: 'modal-backdrop', onclick: () => close(undefined) }), dialog]);
  document.body.appendChild(root);
  document.addEventListener('keydown', onKey);
  const focusTarget = dialog.querySelector('input, textarea, select') || buttons[buttons.length - 1];
  if (focusTarget) setTimeout(() => focusTarget.focus(), 50);
  return { close, root, dialog };
}

export function confirmDialog({ title, message, confirmText = '确定', danger = false }) {
  return new Promise((resolve) => {
    modal({
      title,
      body: h('p', null, message),
      actions: [
        { label: '取消', kind: 'ghost', value: false },
        { label: confirmText, kind: danger ? 'danger' : 'primary', value: true },
      ],
      onClose: (value) => resolve(value === true),
    });
  });
}

// ---------------------------------------------------------------------------
// 表单控件
// ---------------------------------------------------------------------------

export function switchControl({ checked, onChange, label, disabled }) {
  const input = h('input', { type: 'checkbox', checked, disabled, role: 'switch' });
  input.addEventListener('change', () => onChange && onChange(input.checked));
  return h('label', { class: 'switch' }, input, h('span', { class: 'track' }), label ? h('span', { class: 'switch-label' }, label) : null);
}

/** 分段选择：options [[value, label, iconName?]] */
export function segmented(options, value, onChange, { block = false } = {}) {
  const thumb = h('span', { class: 'thumb' });
  const root = h('div', { class: ['segmented', block && 'block'], role: 'tablist' }, thumb);
  const buttons = options.map(([optionValue, label, iconName]) => {
    const button = h('button', { type: 'button', role: 'tab', class: optionValue === value ? 'on' : '' },
      iconName ? icon(iconName) : null, label);
    button.addEventListener('click', () => {
      if (value === optionValue) return;
      value = optionValue;
      update();
      onChange(optionValue);
    });
    root.appendChild(button);
    return [optionValue, button];
  });
  function update() {
    for (const [optionValue, button] of buttons) {
      button.classList.toggle('on', optionValue === value);
      button.setAttribute('aria-selected', optionValue === value ? 'true' : 'false');
    }
    const active = buttons.find(([optionValue]) => optionValue === value);
    if (active) {
      thumb.style.width = active[1].offsetWidth + 'px';
      thumb.style.transform = `translateX(${active[1].offsetLeft - 3}px)`;
    }
  }
  requestAnimationFrame(update);
  if (window.ResizeObserver) new ResizeObserver(update).observe(root);
  root.setValue = (next) => { value = next; update(); };
  return root;
}

/** 密码/密钥输入框，带显示切换 */
export function passwordInput(props = {}) {
  const input = h('input', Object.assign({ class: 'input', type: 'password', autocomplete: 'off', spellcheck: 'false' }, props));
  const toggle = h('button', { type: 'button', class: 'icon-btn sm', 'aria-label': '显示' }, icon('eye'));
  toggle.addEventListener('click', () => {
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    setChildren(toggle, icon(show ? 'eyeOff' : 'eye'));
    toggle.setAttribute('aria-label', show ? '隐藏' : '显示');
  });
  const group = h('div', { class: 'input-group' }, input, toggle);
  group.input = input;
  return group;
}

export function field({ label, help, control, error, extra }) {
  return h('div', { class: ['field', error && 'has-error'] },
    label ? h('label', { class: 'field-label' }, label, extra || null) : null,
    control,
    error ? h('div', { class: 'field-error' }, error) : null,
    help ? h('div', { class: 'field-help' }, help) : null);
}

export function button(label, { kind = '', iconName, onClick, type = 'button', size = '', disabled, title } = {}) {
  const el = h('button', { class: ['btn', kind, size], type, disabled, title }, iconName ? icon(iconName) : null, label);
  if (onClick) {
    el.addEventListener('click', async (event) => {
      if (el.classList.contains('loading')) return;
      const result = onClick(event);
      if (result && typeof result.then === 'function') {
        await withLoading(el, () => result);
      }
    });
  }
  return el;
}

/** 执行异步操作期间让按钮显示加载状态 */
export async function withLoading(buttonEl, fn) {
  const original = Array.from(buttonEl.childNodes);
  buttonEl.classList.add('loading');
  buttonEl.disabled = true;
  const firstIcon = buttonEl.querySelector('svg.icon');
  const spinner = h('span', { class: 'spinner' });
  if (firstIcon) firstIcon.replaceWith(spinner); else buttonEl.prepend(spinner);
  try {
    return await fn();
  } finally {
    buttonEl.classList.remove('loading');
    buttonEl.disabled = false;
    setChildren(buttonEl, original);
  }
}

export function iconButton(name, label, onClick, extra = '') {
  return h('button', { type: 'button', class: `icon-btn ${extra}`, 'aria-label': label, title: label, onclick: onClick }, icon(name));
}

export function pill(text, kind = '', live = false) {
  return h('span', { class: ['pill', kind, live && 'live'] }, h('span', { class: 'dot' }), text);
}

export function emptyState(iconName, title, text) {
  return h('div', { class: 'empty' }, h('div', { class: 'empty-icon' }, icon(iconName)),
    h('div', { class: 'empty-title' }, title), text ? h('div', null, text) : null);
}

export function skeletonCards(count = 3, height = 120) {
  return h('div', { class: 'grid auto' },
    Array.from({ length: count }, () => h('div', { class: 'skeleton block', style: { height: height + 'px' } })));
}

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

export async function copyText(text, what = '内容') {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      // 非 HTTPS 页面不能用 Clipboard API，退回到旧方法
      const area = h('textarea', { class: 'sr-only', readonly: true });
      area.value = text;
      document.body.appendChild(area);
      area.select();
      area.setSelectionRange(0, text.length); // iOS Safari 只认这个
      const okCopy = document.execCommand('copy');
      area.remove();
      if (!okCopy) throw new Error('copy failed');
    }
    toast(`已复制${what}`, 'success', 2000);
  } catch (e) {
    toast('复制失败，请手动选择复制', 'error');
  }
}

export function debounce(fn, wait = 250) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

/** 数字从 0 滚动到目标值 */
export function countUp(el, target, { decimals = 0, suffix = '' } = {}) {
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const format = (value) => value.toLocaleString('zh-CN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + suffix;
  if (reduce || !Number.isFinite(target) || target === 0) { el.textContent = format(target || 0); return; }
  const duration = 800;
  const start = performance.now();
  const tick = (now) => {
    const progress = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = format(target * eased);
    if (progress < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

const pad = (n) => String(n).padStart(2, '0');

export const fmt = {
  time(ts) {
    if (!ts) return '-';
    const d = new Date(ts * 1000);
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  },
  shortTime(ts) {
    if (!ts) return '-';
    const d = new Date(ts * 1000);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    return sameDay ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  },
  relative(ts) {
    if (!ts) return '-';
    const diff = ts - Date.now() / 1000;
    const abs = Math.abs(diff);
    const suffix = diff < 0 ? '前' : '后';
    if (abs < 45) return diff < 0 ? '刚刚' : '马上';
    if (abs < 3600) return `${Math.round(abs / 60)} 分钟${suffix}`;
    if (abs < 86400) return `${Math.round(abs / 3600)} 小时${suffix}`;
    if (abs < 86400 * 30) return `${Math.round(abs / 86400)} 天${suffix}`;
    return fmt.time(ts);
  },
  duration(seconds) {
    seconds = Math.max(0, Math.round(seconds || 0));
    if (seconds < 60) return `${seconds} 秒`;
    if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`;
    if (seconds < 86400) {
      const hours = Math.floor(seconds / 3600);
      const minutes = Math.round((seconds % 3600) / 60);
      return minutes ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`;
    }
    const days = Math.floor(seconds / 86400);
    const hours = Math.round((seconds % 86400) / 3600);
    return hours ? `${days} 天 ${hours} 小时` : `${days} 天`;
  },
  percent(part, total) {
    if (!total) return '-';
    return `${((part / total) * 100).toFixed(part === total ? 0 : 1)}%`;
  },
  number(n) { return Number(n || 0).toLocaleString('zh-CN'); },
};

export const SOURCE_NAMES = { tx: 'QQ 音乐', kg: '酷狗音乐', wy: '网易云音乐' };
export const STATUS = {
  healthy: ['正常', 'ok'],
  degraded: ['降级', 'warn'],
  misconfigured: ['未配置', 'bad'],
  disabled: ['已关闭', ''],
};

export function statusPill(status) {
  const [label, kind] = STATUS[status] || [status || '未知', ''];
  return pill(label, kind, status === 'healthy');
}

// ---------------------------------------------------------------------------
// 主题
// ---------------------------------------------------------------------------

export const theme = {
  get() { return window.__lxTheme ? window.__lxTheme.get() : 'auto'; },
  set(mode) { if (window.__lxTheme) window.__lxTheme.set(mode); },
  next() {
    const order = ['auto', 'light', 'dark'];
    const mode = order[(order.indexOf(theme.get()) + 1) % order.length];
    theme.set(mode);
    return mode;
  },
  icon(mode) { return { auto: 'monitor', light: 'sun', dark: 'moon' }[mode] || 'monitor'; },
  label(mode) { return { auto: '跟随系统', light: '浅色', dark: '深色' }[mode] || '跟随系统'; },
};

export function themeButton() {
  const el = h('button', { type: 'button', class: 'icon-btn' });
  const render = () => {
    const mode = theme.get();
    setChildren(el, icon(theme.icon(mode)));
    el.title = `主题：${theme.label(mode)}(点击切换)`;
    el.setAttribute('aria-label', el.title);
  };
  el.addEventListener('click', () => { const mode = theme.next(); render(); toast(`主题：${theme.label(mode)}`, 'info', 1500); });
  render();
  return el;
}
