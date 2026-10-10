// 概览页

import { h, icon, api, setChildren, stagger, countUp, fmt, statusPill, emptyState, SOURCE_NAMES, pill } from '../core.js';
import { barChart } from '../charts.js';

function greeting() {
  const hour = new Date().getHours();
  if (hour < 6) return '夜深了';
  if (hour < 11) return '早上好';
  if (hour < 14) return '中午好';
  if (hour < 18) return '下午好';
  return '晚上好';
}

function statTile({ label, iconName, value, decimals = 0, suffix = '', foot, kind = '', extra, animate = true }) {
  const valueEl = h('div', { class: 'stat-value' }, '0');
  if (animate) countUp(valueEl, value, { decimals, suffix });
  else valueEl.textContent = Number(value || 0).toLocaleString('zh-CN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + suffix;
  return h('div', { class: ['card', 'stat', 'hover', kind] },
    h('div', { class: 'stat-label' }, icon(iconName), label),
    valueEl, extra || null,
    foot ? h('div', { class: 'stat-foot' }, foot) : null);
}

export function moduleLogo(source) {
  return h('div', { class: `logo ${source}` }, { tx: 'Q', kg: 'K', wy: '网' }[source] || source.slice(0, 1).toUpperCase());
}

function moduleList(modules) {
  if (!modules.length) return emptyState('pulse', '还没有检查结果', '服务启动后会自动检查各平台状态');
  return h('div', { class: 'list' }, modules.map((m) => h('div', { class: 'list-item module-card-sm' },
    moduleLogo(m.source),
    h('div', { class: 'grow' },
      h('div', { class: 'row between' }, h('div', { class: 'list-title' }, m.name || SOURCE_NAMES[m.source] || m.source), statusPill(m.status)),
      h('div', { class: 'list-sub ellipsis', title: m.admin_detail || m.detail || '' }, m.admin_detail || m.detail || '')))));
}

function recentList(logs) {
  if (!logs.length) return emptyState('music', '还没有解析记录', '用户调用解析接口后会显示在这里');
  return h('div', { class: 'list' }, logs.map((log) => h('div', { class: 'list-item' },
    h('div', { class: ['card-icon', log.success ? 'ok' : 'bad'] }, icon(log.success ? 'check' : 'x')),
    h('div', { class: 'grow' },
      h('div', { class: 'list-title ellipsis' },
        `${SOURCE_NAMES[log.source] || log.source || '-'} · ${log.song_id || '-'}`, log.quality ? h('span', { class: 'faint' }, ` · ${log.quality}`) : null),
      h('div', { class: 'list-sub ellipsis' }, `${log.username || '匿名'} · ${log.method || ''}`,
        !log.success && log.error_message ? ` · ${log.error_message}` : '')),
    h('div', { class: 'faint nowrap', title: fmt.time(log.created_at) }, fmt.relative(log.created_at)))));
}

function taskSummary(tasks, navigate) {
  if (!tasks.total) {
    return emptyState('clock', '没有启用的定时任务', '在配置里开启自动刷新登录后会出现在这里');
  }
  if (!tasks.failing.length) {
    return h('div', { class: 'empty' }, h('div', { class: 'empty-icon ok-icon' }, icon('checkCircle')),
      h('div', { class: 'empty-title' }, `${tasks.total} 个定时任务运行正常`),
      h('a', { href: '/admin/health', 'data-link': true }, '查看详情'));
  }
  return h('div', { class: 'stack' },
    h('div', { class: 'notice bad' }, icon('alert'), h('div', null, `${tasks.failing.length} 个任务连续失败，会按退避间隔自动重试`)),
    h('div', { class: 'list' }, tasks.failing.map((t) => h('div', { class: 'list-item' },
      h('div', { class: 'grow' },
        h('div', { class: 'list-title' }, t.label),
        h('div', { class: 'list-sub' }, `连续失败 ${t.consecutive_failures} 次 · 下次重试 ${fmt.relative(t.next_run)}`,
          t.last_error ? ` · ${t.last_error}` : '')),
      pill('失败', 'bad')))),
    h('button', { class: 'btn sm', onclick: () => navigate('/admin/health') }, '去处理', icon('arrowRight')));
}

export async function dashboardPage(ctx) {
  const head = h('div', { class: 'page-head' },
    h('div', null, h('h2', null, `${greeting()}，${ctx.me.username}`), h('p', { class: 'uptime' }, '正在加载服务状态…')),
    h('div', { class: 'actions' },
      h('a', { class: 'btn', href: '/admin/qqlogin', 'data-link': true }, icon('qr'), 'QQ 登录'),
      h('a', { class: 'btn primary', href: '/admin/users?new=1', 'data-link': true }, icon('plus'), '新建用户')));
  const body = h('div', null,
    h('div', { class: 'grid cols-4' }, Array.from({ length: 4 }, () => h('div', { class: 'skeleton block' }))),
    h('div', { class: 'section-gap' }),
    h('div', { class: 'skeleton block' }));
  setChildren(ctx.container, head, body);

  // 首次渲染带入场动画；之后的定时刷新直接替换内容，不再重复播放动画
  const render = (data, animate) => {
    body.classList.toggle('no-anim', !animate);
    const tile = (options) => statTile(Object.assign({ animate }, options));
    head.querySelector('.uptime').textContent = `服务已运行 ${fmt.duration(data.uptime)}` +
      (data.cookiepool ? ' · 账号池模式' : '') + (data.key_enabled ? '' : ' · ⚠ 接口未开启 Key 鉴权');
    const today = data.today;
    const tiles = stagger(h('div', { class: 'grid cols-4' },
      tile({ label: '今日解析', iconName: 'zap', value: today.total, foot: `成功 ${today.success} · 失败 ${today.failure}` }),
      tile({
        label: '今日成功率', iconName: 'checkCircle', kind: today.total && today.failure / today.total > 0.3 ? 'warn' : 'ok',
        value: today.total ? (today.success / today.total) * 100 : 0, decimals: today.total ? 1 : 0, suffix: today.total ? '%' : '',
        extra: h('div', { class: 'progress ok' }, h('span', { style: { width: `${today.total ? (today.success / today.total) * 100 : 0}%` } })),
      }),
      tile({ label: '近 7 天解析', iconName: 'chart', value: data.week.total, foot: `${data.week.users} 位用户使用过` }),
      tile({ label: 'API 用户', iconName: 'users', value: data.users.enabled, foot: `共 ${data.users.total} 位，${data.users.total - data.users.enabled} 位已停用` })));

    const charts = stagger(h('div', { class: 'grid cols-3' },
      h('section', { class: 'card span-2' },
        h('div', { class: 'card-header' },
          h('div', { class: 'grow' }, h('h3', { class: 'card-title' }, '近 7 天解析趋势'), h('p', { class: 'card-sub' }, '每天的成功与失败次数')),
          h('div', { class: 'chart-legend' }, h('span', null, h('i'), '成功'), h('span', null, h('i', { class: 'bad' }), '失败'))),
        h('div', { class: 'card-body' }, barChart(data.daily))),
      h('section', { class: 'card' },
        h('div', { class: 'card-header' }, h('div', { class: 'grow' }, h('h3', { class: 'card-title' }, '平台状态')),
          h('a', { class: 'btn ghost sm', href: '/admin/health', 'data-link': true }, '详情', icon('arrowRight'))),
        h('div', { class: 'card-body' }, moduleList(data.modules)))));

    const lower = stagger(h('div', { class: 'grid cols-2' },
      h('section', { class: 'card' },
        h('div', { class: 'card-header' }, h('div', { class: 'grow' }, h('h3', { class: 'card-title' }, '最近解析')),
          h('a', { class: 'btn ghost sm', href: '/admin/stats', 'data-link': true }, '全部', icon('arrowRight'))),
        h('div', { class: 'card-body' }, recentList(data.recent))),
      h('section', { class: 'card' },
        h('div', { class: 'card-header' }, h('div', { class: 'grow' }, h('h3', { class: 'card-title' }, '定时任务'))),
        h('div', { class: 'card-body' }, taskSummary(data.tasks, ctx.navigate)))));

    setChildren(body, tiles, h('div', { class: 'section-gap' }), charts, h('div', { class: 'section-gap' }), lower);
  };

  render(await api('GET', '/api/admin/overview'), true);
  ctx.every(async () => {
    try {
      const data = await api('GET', '/api/admin/overview');
      if (ctx.alive()) render(data, false);
    } catch (e) { /* 自动刷新失败时保留当前内容 */ }
  }, 30000);
}
