// 模块状态与定时任务

import { h, icon, api, setChildren, toast, stagger, fmt, statusPill, emptyState, pill, withLoading, SOURCE_NAMES } from '../core.js';
import { moduleLogo } from './dashboard.js';

export async function healthPage(ctx) {
  const refreshButton = h('button', { class: 'btn primary' }, icon('refresh'), '立即检查');
  const head = h('div', { class: 'page-head' },
    h('div', null, h('h2', null, '模块状态'), h('p', null, '各平台是否可用、账号凭证是否有效，以及登录保活等定时任务的运行情况')),
    h('div', { class: 'actions' }, refreshButton));
  const modulesEl = h('div', { class: 'grid cols-3' }, Array.from({ length: 3 }, () => h('div', { class: 'skeleton block' })));
  const tasksBody = h('div', { class: 'card-body' }, h('div', { class: 'skeleton block' }));
  setChildren(ctx.container, head, modulesEl, h('div', { class: 'section-gap' }),
    h('section', { class: 'card' },
      h('div', { class: 'card-header' }, h('div', { class: 'card-icon' }, icon('clock')),
        h('div', { class: 'grow' }, h('h3', { class: 'card-title' }, '定时任务'),
          h('p', { class: 'card-sub' }, '失败后按 1 分钟、5 分钟、30 分钟、2 小时退避重试(不超过任务自身的间隔)'))),
      tasksBody));

  let first = true;
  const render = (data) => {
    const cards = data.modules.map((m) => h('section', { class: ['card', 'hover', m.status === 'disabled' && 'dimmed'] },
      h('div', { class: 'card-body stack' },
        h('div', { class: 'row' }, moduleLogo(m.source),
          h('div', { class: 'grow' }, h('div', { class: 'list-title' }, m.name || SOURCE_NAMES[m.source] || m.source),
            h('div', { class: 'list-sub', title: fmt.time(m.checked_at) }, `检查于 ${fmt.relative(m.checked_at)}`)),
          statusPill(m.status)),
        h('div', { class: 'muted' }, m.detail || ''),
        m.admin_detail ? h('div', { class: 'notice warn' }, icon('alert'), h('div', null, m.admin_detail)) : null,
        m.status === 'misconfigured' || m.status === 'disabled'
          ? h('a', { class: 'btn sm', href: `/admin/config#${m.source}`, 'data-link': true }, icon('sliders'), '去配置') : null)));
    setChildren(modulesEl, cards.length ? cards : h('div', { class: 'card span-2' }, emptyState('pulse', '还没有检查结果', '点击「立即检查」')));
    if (first) stagger(modulesEl);

    if (!data.tasks.length) {
      setChildren(tasksBody, emptyState('clock', '没有启用的定时任务', '在「配置」里开启各平台的自动刷新登录后会出现在这里'));
    } else {
      const rows = data.tasks.map((t) => {
        let status;
        if (t.running) status = pill('执行中', 'brand', true);
        else if (t.consecutive_failures) status = pill(`连续失败 ${t.consecutive_failures} 次`, 'bad');
        else if (t.last_success_at) status = pill('正常', 'ok');
        else status = pill('等待首次执行', '');
        const runButton = h('button', { class: 'btn sm', disabled: t.running }, icon('play'), '立即执行');
        runButton.addEventListener('click', () => withLoading(runButton, async () => {
          try {
            await api('POST', `/api/admin/tasks/${encodeURIComponent(t.name)}/run`);
            toast(`「${t.label}」将在几秒内执行`, 'success', 2500);
            setTimeout(reload, 2500);
          } catch (e) { toast(e.message, 'error'); }
        }));
        return h('tr', null,
          h('td', { class: 'primary', 'data-label': '任务' }, h('div', null, h('div', { class: 'list-title' }, t.label),
            h('div', { class: 'list-sub mono' }, t.name))),
          h('td', { 'data-label': '状态' }, status),
          h('td', { 'data-label': '间隔' }, fmt.duration(t.interval)),
          h('td', { 'data-label': '上次成功', title: fmt.time(t.last_success_at) }, t.last_success_at ? fmt.relative(t.last_success_at) : '-'),
          h('td', { 'data-label': '下次执行', title: fmt.time(t.next_run) }, t.running ? '-' : (t.next_run ? fmt.relative(t.next_run) : '马上')),
          h('td', { 'data-label': '最近错误', class: 'task-error' }, t.last_error ? h('span', { class: 'bad-text', title: t.last_error }, t.last_error) : h('span', { class: 'faint' }, '无')),
          h('td', { 'data-label': '操作', class: 'num' }, runButton));
      });
      setChildren(tasksBody, h('div', { class: 'table-wrap' }, h('table', { class: 'table responsive' },
        h('thead', null, h('tr', null, ['任务', '状态', '间隔', '上次成功', '下次执行', '最近错误', ''].map((t) => h('th', null, t)))),
        h('tbody', null, rows))));
    }
    first = false;
  };

  const reload = async () => {
    try {
      const data = await api('GET', '/api/admin/health');
      if (ctx.alive()) render(data);
    } catch (e) { /* 保留当前内容 */ }
  };

  refreshButton.addEventListener('click', () => withLoading(refreshButton, async () => {
    try {
      render(await api('POST', '/api/admin/health/refresh'));
      ctx.refreshBadges();
      toast('已重新检查所有模块', 'success', 2000);
    } catch (e) { toast(e.message, 'error'); }
  }));

  render(await api('GET', '/api/admin/health'));
  ctx.every(reload, 15000);
}
