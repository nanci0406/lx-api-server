// 管理员账号：资料、会话、修改密码

import { h, icon, api, setChildren, toast, confirmDialog, passwordInput, field, fmt, withLoading } from '../core.js';

function strength(password) {
  let score = 0;
  if (password.length >= 8) score += 1;
  if (password.length >= 12) score += 1;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1;
  if (/\d/.test(password)) score += 1;
  if (/[^A-Za-z0-9]/.test(password)) score += 1;
  if (password.length < 8) return [Math.min(score, 1), '太短', 'bad'];
  if (score <= 2) return [2, '一般', 'warn'];
  if (score <= 3) return [3, '较强', 'ok'];
  return [5, '很强', 'ok'];
}

export async function accountPage(ctx) {
  const profileBody = h('div', { class: 'card-body' }, h('div', { class: 'skeleton block' }));
  const current = passwordInput({ autocomplete: 'current-password', placeholder: '当前密码' });
  const next = passwordInput({ autocomplete: 'new-password', placeholder: '至少 8 位' });
  const confirm = passwordInput({ autocomplete: 'new-password', placeholder: '再输入一次新密码' });
  const meter = h('div', { class: 'strength' }, h('div', { class: 'progress' }, h('span')), h('span', { class: 'strength-text faint' }, ''));
  const error = h('div', { class: 'field-error', role: 'alert' });
  const submit = h('button', { class: 'btn primary', type: 'submit' }, icon('check'), '修改密码');

  next.input.addEventListener('input', () => {
    const value = next.input.value;
    const [score, label, kind] = strength(value);
    const bar = meter.querySelector('.progress');
    bar.className = `progress ${kind === 'ok' ? 'ok' : ''}`;
    const span = bar.querySelector('span');
    span.style.width = value ? `${(score / 5) * 100}%` : '0';
    span.style.background = kind === 'bad' ? 'var(--bad)' : (kind === 'warn' ? 'var(--warn)' : '');
    meter.querySelector('.strength-text').textContent = value ? `强度：${label}` : '';
  });

  const form = h('form', { class: 'stack', novalidate: true },
    field({ label: '当前密码', control: current }),
    field({ label: '新密码', control: next, help: '至少 8 位；修改后，其他设备上的登录会自动退出' }),
    meter,
    field({ label: '确认新密码', control: confirm }),
    error,
    h('div', null, submit));
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    error.textContent = '';
    if (!current.input.value) { error.textContent = '请输入当前密码'; current.input.focus(); return; }
    if (next.input.value.trim().length < 8) { error.textContent = '新密码至少需要 8 位'; next.input.focus(); return; }
    if (next.input.value !== confirm.input.value) { error.textContent = '两次输入的新密码不一致'; confirm.input.focus(); return; }
    await withLoading(submit, async () => {
      try {
        await api('POST', '/api/admin/account/password', { current: current.input.value, new: next.input.value });
        form.reset();
        next.input.dispatchEvent(new Event('input'));
        toast('密码已修改，其他设备上的登录已退出', 'success');
        loadProfile();
      } catch (e) {
        error.textContent = e.message;
      }
    });
  });

  setChildren(ctx.container,
    h('div', { class: 'page-head' }, h('div', null, h('h2', null, '账号安全'), h('p', null, '管理员资料、登录会话和密码'))),
    h('div', { class: 'grid cols-2' },
      h('section', { class: 'card' }, h('div', { class: 'card-header' }, h('div', { class: 'card-icon' }, icon('user')),
        h('h3', { class: 'card-title' }, '管理员')), profileBody),
      h('section', { class: 'card' }, h('div', { class: 'card-header' }, h('div', { class: 'card-icon' }, icon('lock')),
        h('h3', { class: 'card-title' }, '修改密码')), h('div', { class: 'card-body' }, form))));

  async function loadProfile() {
    const me = await api('GET', '/api/admin/me');
    if (!ctx.alive()) return;
    ctx.setMe(me);
    const others = me.other_sessions || 0;
    const logoutOthers = h('button', { class: 'btn sm', disabled: !others }, icon('logout'), '退出其他设备');
    logoutOthers.addEventListener('click', async () => {
      if (!(await confirmDialog({ title: '退出其他设备', message: `将退出这个账号在其他设备或浏览器上的 ${others} 个登录。`, confirmText: '退出' }))) return;
      await withLoading(logoutOthers, async () => {
        try {
          const data = await api('POST', '/api/admin/account/logout-others', {});
          toast(`已退出 ${data.closed} 个其他登录`, 'success');
          loadProfile();
        } catch (e) { toast(e.message, 'error'); }
      });
    });
    setChildren(profileBody, h('div', { class: 'stack' },
      h('div', { class: 'row' }, h('div', { class: 'avatar lg' }, me.username.slice(0, 1)),
        h('div', null, h('div', { class: 'list-title' }, me.username), h('div', { class: 'list-sub' }, '管理员'))),
      h('dl', { class: 'kv' },
        h('dt', null, '账号创建'), h('dd', null, fmt.time(me.created_at)),
        h('dt', null, '最近登录'), h('dd', null, me.last_login_at ? `${fmt.time(me.last_login_at)}（${fmt.relative(me.last_login_at)}）` : '-'),
        h('dt', null, '本次登录'), h('dd', null, fmt.time(me.session_started_at)),
        h('dt', null, '其他会话'), h('dd', null, others ? `${others} 个其他设备/浏览器在登录中` : '没有')),
      h('div', { class: 'row wrap' }, logoutOthers),
      h('div', { class: 'notice' }, icon('info'), h('div', null, '后台登录 4 小时无操作或登录满 24 小时后需要重新登录；同一 IP 15 分钟内登录失败 5 次会被暂时限制。'))));
  }
  await loadProfile();
}
