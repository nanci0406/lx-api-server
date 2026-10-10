// 解析统计页

import { h, icon, api, setChildren, segmented, stagger, countUp, fmt, emptyState, pill, toast, SOURCE_NAMES } from '../core.js';
import { barChart, hbars } from '../charts.js';

const RANGES = [[1, '今天'], [7, '近 7 天'], [30, '近 30 天']];
const PAGE_SIZE = 30;

function tile(label, iconName, value, { kind = '', foot, decimals = 0, suffix = '' } = {}) {
  const el = h('div', { class: 'stat-value' });
  countUp(el, value, { decimals, suffix });
  return h('div', { class: ['card', 'stat', kind] }, h('div', { class: 'stat-label' }, icon(iconName), label), el,
    foot ? h('div', { class: 'stat-foot' }, foot) : null);
}

export async function statsPage(ctx) {
  let days = Number(ctx.query.get('days')) || 7;
  if (![1, 7, 30].includes(days)) days = 7;
  const filters = { username: '', source: '', result: '' };
  let logs = [];
  let total = 0;
  let users = [];

  const range = segmented(RANGES, days, (value) => {
    days = value;
    history.replaceState(null, '', `${location.pathname}?days=${value}`);
    loadOverview().catch((e) => toast(e.message, 'error'));
  });
  const head = h('div', { class: 'page-head' },
    h('div', null, h('h2', null, '统计'), h('p', null, '解析接口的调用情况；超过保留天数的记录会被自动清理')),
    h('div', { class: 'actions' }, range));
  const overview = h('div', null, h('div', { class: 'grid cols-4' }, Array.from({ length: 4 }, () => h('div', { class: 'skeleton block' }))));

  const userSelect = h('select', { class: 'select', 'aria-label': '按用户筛选' });
  const sourceSelect = h('select', { class: 'select', 'aria-label': '按平台筛选' },
    h('option', { value: '' }, '全部平台'), Object.entries(SOURCE_NAMES).map(([id, name]) => h('option', { value: id }, name)));
  const resultSelect = h('select', { class: 'select', 'aria-label': '按结果筛选' },
    h('option', { value: '' }, '全部结果'), h('option', { value: 'success' }, '成功'), h('option', { value: 'failure' }, '失败'));
  const logBody = h('div');
  const moreButton = h('button', { class: 'btn block' }, '加载更多');
  const logInfo = h('span', { class: 'faint' });
  const logsCard = h('section', { class: 'card', id: 'logs' },
    h('div', { class: 'card-header' }, h('div', { class: 'grow row' }, h('h3', { class: 'card-title' }, '解析记录'), logInfo),
      h('div', { class: 'filters' }, userSelect, sourceSelect, resultSelect)),
    h('div', { class: 'card-body stack' }, logBody, moreButton));

  setChildren(ctx.container, head, overview, h('div', { class: 'section-gap' }), logsCard);

  for (const [select, keyName] of [[userSelect, 'username'], [sourceSelect, 'source'], [resultSelect, 'result']]) {
    select.addEventListener('change', () => { filters[keyName] = select.value; loadLogs(true).catch((e) => toast(e.message, 'error')); });
  }
  moreButton.addEventListener('click', async () => {
    moreButton.disabled = true;
    moreButton.textContent = '加载中…';
    try { await loadLogs(false); } catch (e) { toast(e.message, 'error'); } finally { moreButton.disabled = false; updateMore(); }
  });

  function updateMore() {
    moreButton.classList.toggle('hidden', logs.length >= total);
    moreButton.textContent = `加载更多（已显示 ${logs.length} / ${total}）`;
  }

  function renderUserOptions() {
    const names = Array.from(new Set(users.map((u) => u.username).filter(Boolean)));
    if (filters.username && !names.includes(filters.username)) names.unshift(filters.username);
    userSelect.replaceChildren(h('option', { value: '' }, '全部用户'), names.map((name) => h('option', { value: name }, name)));
    userSelect.value = filters.username;
  }

  async function loadOverview() {
    overview.classList.add('loading-fade');
    let data;
    try {
      data = await api('GET', `/api/admin/stats?days=${days}`);
    } finally {
      overview.classList.remove('loading-fade');
    }
    if (!ctx.alive()) return;
    users = data.by_user;
    renderUserOptions();
    const t = data.totals;
    const rate = t.total ? (t.success / t.total) * 100 : 0;
    const rangeLabel = RANGES.find(([value]) => value === days)[1];
    const tiles = stagger(h('div', { class: 'grid cols-4' },
      tile('解析次数', 'zap', t.total, { foot: rangeLabel }),
      tile('成功率', 'chart', rate, { decimals: t.total ? 1 : 0, suffix: t.total ? '%' : '', kind: t.total && rate < 70 ? 'warn' : 'ok',
        foot: `成功 ${fmt.number(t.success)} · 失败 ${fmt.number(t.failure)}` }),
      tile('失败', 'xCircle', t.failure, { kind: t.failure ? 'bad' : '', foot: t.failure ? '可在下方记录里查看原因' : '没有失败' }),
      tile('活跃用户', 'users', t.users, { foot: '有解析记录的用户' })));
    const sources = data.by_source.length
      ? hbars(data.by_source.map((row) => ({ label: row.name || SOURCE_NAMES[row.source] || row.source, value: row.total,
        text: `${fmt.number(row.total)} · ${fmt.percent(row.success, row.total)}` })))
      : emptyState('music', '暂无数据');
    const ranking = data.by_user.length
      ? h('div', { class: 'table-wrap' }, h('table', { class: 'table responsive' },
        h('thead', null, h('tr', null, h('th', null, '用户'), h('th', { class: 'num' }, '次数'), h('th', { class: 'num' }, '成功率'), h('th', null, '最近'))),
        h('tbody', null, data.by_user.slice(0, 10).map((row) => h('tr', {
          class: 'clickable', title: '查看这位用户的解析记录',
          onclick: () => {
            filters.username = row.username;
            renderUserOptions();
            loadLogs(true).catch((e) => toast(e.message, 'error'));
            logsCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
          },
        },
        h('td', { class: 'primary', 'data-label': '用户' }, h('div', { class: 'row' }, h('div', { class: 'avatar' }, (row.username || '?').slice(0, 1)),
          h('span', { class: 'list-title' }, row.username || '(匿名)'))),
        h('td', { class: 'num', 'data-label': '次数' }, fmt.number(row.total)),
        h('td', { class: 'num', 'data-label': '成功率' }, fmt.percent(row.success, row.total)),
        h('td', { 'data-label': '最近' }, fmt.relative(row.last_at)))))))
      : emptyState('users', '暂无数据');

    setChildren(overview, tiles, h('div', { class: 'section-gap' }),
      stagger(h('div', { class: 'grid cols-3' },
        h('section', { class: 'card span-2' },
          h('div', { class: 'card-header' }, h('div', { class: 'grow' }, h('h3', { class: 'card-title' }, '每日趋势')),
            h('div', { class: 'chart-legend' }, h('span', null, h('i'), '成功'), h('span', null, h('i', { class: 'bad' }), '失败'))),
          h('div', { class: 'card-body' }, barChart(data.daily))),
        h('section', { class: 'card' },
          h('div', { class: 'card-header' }, h('h3', { class: 'card-title' }, '平台分布')),
          h('div', { class: 'card-body' }, sources)))),
      h('div', { class: 'section-gap' }),
      h('section', { class: 'card' },
        h('div', { class: 'card-header' }, h('div', { class: 'grow' }, h('h3', { class: 'card-title' }, '用户排行'),
          h('p', { class: 'card-sub' }, '点击用户查看 TA 的解析记录'))),
        h('div', { class: 'card-body' }, ranking)));
  }

  async function loadLogs(reset) {
    const offset = reset ? 0 : logs.length;
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    for (const [keyName, value] of Object.entries(filters)) if (value) params.set(keyName, value);
    if (reset) logBody.classList.add('loading-fade');
    let data;
    try {
      data = await api('GET', `/api/admin/stats/logs?${params}`);
    } finally {
      logBody.classList.remove('loading-fade');
    }
    if (!ctx.alive()) return;
    logs = reset ? data.logs : logs.concat(data.logs);
    total = data.total;
    renderLogs(reset ? 0 : offset);
  }

  function logRow(log) {
    return h('tr', null,
      h('td', { class: 'primary', 'data-label': '时间' }, h('div', { class: 'row' },
        h('div', { class: ['card-icon', log.success ? 'ok' : 'bad'] }, icon(log.success ? 'check' : 'x')),
        h('div', null, h('div', { class: 'list-title' }, `${SOURCE_NAMES[log.source] || log.source || '-'} · ${log.method || '-'}`),
          h('div', { class: 'list-sub', title: fmt.time(log.created_at) }, fmt.time(log.created_at))))),
      h('td', { 'data-label': '用户' }, log.username || h('span', { class: 'faint' }, '匿名')),
      h('td', { 'data-label': '歌曲 ID', class: 'mono ellipsis' }, log.song_id || '-'),
      h('td', { 'data-label': '音质' }, log.quality || '-'),
      h('td', { 'data-label': '结果' }, log.success ? pill('成功', 'ok') : h('div', { class: 'stack tight log-error' }, pill('失败', 'bad'),
        log.error_message ? h('span', { class: 'list-sub', title: log.error_message }, log.error_message) : null)),
      h('td', { 'data-label': 'IP', class: 'mono faint' }, log.client_ip || '-'));
  }

  function renderLogs(animateFrom) {
    logInfo.textContent = total ? `共 ${fmt.number(total)} 条` : '';
    updateMore();
    if (!logs.length) {
      setChildren(logBody, emptyState('file', Object.values(filters).some(Boolean) ? '没有符合条件的记录' : '还没有解析记录'));
      return;
    }
    const rows = logs.map(logRow);
    rows.slice(animateFrom).forEach((row, index) => { row.classList.add('row-in'); row.style.setProperty('--i', String(Math.min(index, 15))); });
    setChildren(logBody, h('div', { class: 'table-wrap' }, h('table', { class: 'table responsive' },
      h('thead', null, h('tr', null, ['时间', '用户', '歌曲 ID', '音质', '结果', 'IP'].map((t) => h('th', null, t)))),
      h('tbody', null, rows))));
  }

  await Promise.all([loadOverview(), loadLogs(true)]);
}
