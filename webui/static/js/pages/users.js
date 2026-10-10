// 用户管理页

import {
  h, icon, api, setChildren, toast, modal, confirmDialog, switchControl, field, copyText, fmt, emptyState, iconButton,
  stagger,
} from '../core.js';

function randomKey() {
  const bytes = new Uint8Array(18);
  crypto.getRandomValues(bytes);
  let text = '';
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function scriptUrl(key) {
  return `${location.origin}/script?key=${encodeURIComponent(key)}`;
}

function codeBox(value, { what, masked = false, wrap = false } = {}) {
  let show = !masked;
  const text = h('span', { class: ['value', wrap && 'wrap'] });
  const render = () => { text.textContent = show ? value : `••••••••${value.slice(-4)}`; };
  const toggle = masked ? iconButton('eye', '显示/隐藏', () => {
    show = !show;
    render();
    toggle.replaceChildren(icon(show ? 'eyeOff' : 'eye'));
  }, 'sm') : null;
  render();
  return h('div', { class: 'code-box' }, text, toggle, iconButton('copy', `复制${what || ''}`, () => copyText(value, what), 'sm'));
}

/** 创建用户、重置 Key 之后展示新 Key 和脚本链接 */
function showCredentials(user, scriptEnabled, title) {
  modal({
    title,
    body: h('div', { class: 'stack' },
      h('div', { class: 'row' }, h('div', { class: 'avatar' }, user.name.slice(0, 1)),
        h('div', null, h('div', { class: 'list-title' }, user.name), h('div', { class: 'list-sub' }, '请把下面的信息发给这位用户'))),
      field({ label: '用户名', control: codeBox(user.name, { what: '用户名' }) }),
      field({ label: 'Key', control: codeBox(user.api_key, { what: ' Key' }) }),
      scriptEnabled ? field({ label: 'LX Music 音源脚本链接', control: codeBox(scriptUrl(user.api_key), { what: '脚本链接', wrap: true }),
        help: '在 LX Music「设置 → 自定义源」里导入这个链接即可' }) : null),
    actions: [{ label: '完成', kind: 'primary' }],
  });
}

export async function usersPage(ctx) {
  let data = { users: [], script_enabled: false, key_enabled: true };
  let filter = '';

  const search = h('input', { class: 'input', type: 'search', placeholder: '搜索用户名', 'aria-label': '搜索用户名' });
  const head = h('div', { class: 'page-head' },
    h('div', null, h('h2', null, '用户'), h('p', null, '每位用户使用「用户名 + Key」调用解析接口、下载音源脚本')),
    h('div', { class: 'actions' }, h('button', { class: 'btn primary', onclick: openCreate }, icon('plus'), '新建用户')));
  const notices = h('div');
  const listBody = h('div', { class: 'card-body' }, h('div', { class: 'stack' },
    Array.from({ length: 4 }, () => h('div', { class: 'skeleton line' }))));
  const countText = h('span', { class: 'faint' });
  setChildren(ctx.container, head, notices,
    h('section', { class: 'card' },
      h('div', { class: 'card-header' }, h('div', { class: 'grow row' }, h('h3', { class: 'card-title' }, '用户列表'), countText),
        h('div', { class: 'search-box' }, icon('search'), search)),
      listBody));
  search.addEventListener('input', () => { filter = search.value.trim().toLowerCase(); renderList(); });

  async function load() {
    data = await api('GET', '/api/admin/users');
    renderNotices();
    renderList();
  }

  function renderNotices() {
    setChildren(notices,
      !data.key_enabled ? h('div', { class: 'notice warn' }, icon('alert'),
        h('div', null, '接口目前没有开启 Key 鉴权，任何人都可以调用解析接口。可以在 ', h('a', { href: '/admin/config#security', 'data-link': true }, '配置 → 安全'), ' 里开启。')) : null,
      !data.key_enabled ? h('div', { class: 'section-gap' }) : null);
  }

  function renderList() {
    const users = data.users.filter((u) => !filter || u.name.toLowerCase().includes(filter));
    countText.textContent = data.users.length ? `共 ${data.users.length} 位` : '';
    if (!data.users.length) {
      setChildren(listBody, h('div', { class: 'empty' },
        h('div', { class: 'empty-icon' }, icon('users')), h('div', { class: 'empty-title' }, '还没有用户'),
        h('div', null, '新建一位用户，把用户名和 Key 发给 TA 就能使用了'),
        h('button', { class: 'btn primary', onclick: openCreate }, icon('plus'), '新建用户')));
      return;
    }
    if (!users.length) { setChildren(listBody, emptyState('search', '没有匹配的用户')); return; }
    const tbody = stagger(h('tbody', null, users.map(userRow)));
    setChildren(listBody, h('div', { class: 'table-wrap' }, h('table', { class: 'table responsive' },
      h('thead', null, h('tr', null, h('th', null, '用户'), h('th', null, '启用'), h('th', null, 'Key'), h('th', { class: 'num' }, '解析次数'),
        h('th', null, '最近使用'), h('th', { class: 'num' }, '操作'))),
      tbody)));
  }

  function userRow(user) {
    const rate = user.total ? fmt.percent(user.success_count, user.total) : '-';
    const toggle = switchControl({
      checked: Boolean(user.enabled),
      onChange: async (checked) => {
        try {
          await api('PATCH', `/api/admin/users/${user.id}`, { enabled: checked });
          user.enabled = checked ? 1 : 0;
          toast(checked ? `已启用 ${user.name}` : `已停用 ${user.name}，TA 将无法继续使用`, checked ? 'success' : 'warn', 2500);
        } catch (e) {
          toggle.querySelector('input').checked = !checked;
          toast(e.message, 'error');
        }
      },
    });
    const actions = h('div', { class: 'actions' },
      data.script_enabled ? iconButton('link', '复制音源脚本链接', () => copyText(scriptUrl(user.api_key), '脚本链接'), 'sm') : null,
      iconButton('rotate', '重置 Key', () => resetKey(user), 'sm'),
      iconButton('trash', '删除用户', () => removeUser(user), 'sm danger'));
    return h('tr', null,
      h('td', { class: 'primary', 'data-label': '用户' }, h('div', { class: 'row' }, h('div', { class: 'avatar' }, user.name.slice(0, 1)),
        h('div', { class: 'grow' }, h('div', { class: 'list-title ellipsis' }, user.name),
          h('div', { class: 'list-sub' }, `创建于 ${fmt.time(user.created_at).slice(0, 10)}`)))),
      h('td', { 'data-label': '启用' }, toggle),
      h('td', { 'data-label': 'Key', class: 'key-cell' }, codeBox(user.api_key, { what: ' Key', masked: true })),
      h('td', { 'data-label': '解析次数', class: 'num' }, h('div', null, h('div', null, fmt.number(user.total)),
        user.total ? h('div', { class: 'list-sub' }, `成功率 ${rate}`) : null)),
      h('td', { 'data-label': '最近使用', title: fmt.time(user.last_used_at) }, user.last_used_at ? fmt.relative(user.last_used_at) : h('span', { class: 'faint' }, '从未使用')),
      h('td', { 'data-label': '操作', class: 'num' }, actions));
  }

  function openCreate() {
    const name = h('input', { class: 'input', placeholder: '例如 alice', autocomplete: 'off', spellcheck: 'false', maxlength: 32 });
    const key = h('input', { class: 'input mono', placeholder: '留空自动生成', autocomplete: 'off', spellcheck: 'false', maxlength: 64 });
    const generate = iconButton('sparkles', '随机生成', () => { key.value = randomKey(); key.focus(); }, 'sm');
    const error = h('div', { class: 'field-error' });
    const submit = async () => {
      error.textContent = '';
      try {
        const user = await api('POST', '/api/admin/users', { name: name.value.trim(), api_key: key.value.trim() });
        await load();
        showCredentials(user, data.script_enabled, '用户已创建');
        return true;
      } catch (e) {
        error.textContent = e.message;
        return false;
      }
    };
    const form = h('form', { class: 'stack', onsubmit: (event) => { event.preventDefault(); dialog.dialog.querySelector('.btn.primary').click(); } },
      field({ label: '用户名', control: name, help: '1～32 位，可以使用字母、数字和 _ . @ -' }),
      field({ label: 'Key', control: h('div', { class: 'input-group' }, key, generate), help: '6～64 位；不填会自动生成一个安全的随机 Key' }),
      error,
      h('button', { type: 'submit', class: 'sr-only', tabindex: '-1' }, '提交'));
    const dialog = modal({
      title: '新建用户',
      body: form,
      actions: [{ label: '取消', kind: 'ghost' }, { label: '创建', kind: 'primary', onClick: submit }],
    });
  }

  async function resetKey(user) {
    const okReset = await confirmDialog({ title: `重置 ${user.name} 的 Key`, confirmText: '重置',
      message: '重置后旧 Key 和旧的音源脚本链接立即失效，需要把新的 Key 发给这位用户。' });
    if (!okReset) return;
    try {
      const updated = await api('POST', `/api/admin/users/${user.id}/reset-key`, {});
      await load();
      showCredentials(updated, data.script_enabled, 'Key 已重置');
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  async function removeUser(user) {
    const okDelete = await confirmDialog({ title: `删除用户 ${user.name}`, confirmText: '删除', danger: true,
      message: '删除后这位用户将无法再使用，此操作不能撤销。历史解析记录会保留。' });
    if (!okDelete) return;
    try {
      await api('DELETE', `/api/admin/users/${user.id}`);
      data.users = data.users.filter((u) => u.id !== user.id);
      renderList();
      toast(`已删除 ${user.name}`, 'success', 2500);
    } catch (e) {
      toast(e.message, 'error');
    }
  }

  await load();
  if (ctx.query.get('new') === '1' && ctx.alive()) {
    history.replaceState(null, '', location.pathname);
    openCreate();
  }
}
