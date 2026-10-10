// 简单的 SVG 柱状图(按天统计的成功/失败次数)，随容器宽度自动重绘

import { h, svg, setChildren } from './core.js';

function niceMax(value) {
  if (value <= 4) return 4;
  const power = Math.pow(10, Math.floor(Math.log10(value)));
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (step * power >= value) return step * power;
  }
  return 10 * power;
}

function dayLabel(day) {
  const [, month, date] = day.split('-');
  return `${Number(month)}/${Number(date)}`;
}

// 页面上同一时间只有一个提示框；图表被替换(定时刷新、切换页面)或页面滚动时收起
let tip = null;
const hideTip = () => { if (tip) { tip.remove(); tip = null; } };
document.addEventListener('touchstart', (event) => { if (!event.target.closest('.chart-wrap')) hideTip(); }, { passive: true });
window.addEventListener('scroll', hideTip, { passive: true });

function showTip(target, row) {
  hideTip();
  const failure = row.total - row.success;
  tip = h('div', { class: 'chart-tip' },
    h('div', null, h('b', null, row.day)),
    h('div', null, `解析 ${row.total} 次`),
    h('div', null, `成功 ${row.success}　失败 ${failure}`));
  document.body.appendChild(tip);
  const rect = target.getBoundingClientRect();
  tip.style.left = `${rect.left + rect.width / 2}px`;
  tip.style.top = `${rect.top}px`;
}

/** data: [{day: 'YYYY-MM-DD', total, success}] */
export function barChart(data, { height = 220 } = {}) {
  const wrap = h('div', { class: 'chart-wrap' });
  let lastWidth = 0;
  hideTip();

  const draw = () => {
    const width = Math.max(260, Math.floor(wrap.clientWidth || 600));
    if (width === lastWidth) return;
    lastWidth = width;
    const pad = { top: 12, right: 6, bottom: 26, left: 34 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const max = niceMax(Math.max(0, ...data.map((row) => row.total)));
    const n = Math.max(1, data.length);
    const slot = plotW / n;
    const barW = Math.max(6, Math.min(34, slot * 0.58));
    const labelEvery = Math.max(1, Math.ceil(n / Math.max(4, Math.floor(plotW / 56))));

    const root = svg('svg', { class: 'chart', viewBox: `0 0 ${width} ${height}`, width, height, role: 'img',
      'aria-label': '每日解析次数柱状图' });
    for (let i = 0; i <= 4; i++) {
      const y = pad.top + plotH - (plotH * i) / 4;
      root.append(svg('line', { class: 'grid-line', x1: pad.left, x2: width - pad.right, y1: y, y2: y }));
      root.append(svg('text', { class: 'axis-label', x: pad.left - 8, y: y + 4, 'text-anchor': 'end' },
        String(Math.round((max * i) / 4))));
    }
    data.forEach((row, index) => {
      const x = pad.left + slot * index + (slot - barW) / 2;
      const failure = Math.max(0, row.total - row.success);
      const okH = (row.success / max) * plotH;
      const badH = (failure / max) * plotH;
      const base = pad.top + plotH;
      const group = svg('g', { class: 'bar-group' });
      group.style.setProperty('--i', String(index)); // 不能写 style 属性：CSP 禁止内联样式，CSSOM 不受限制
      if (okH > 0) group.append(svg('rect', { class: 'bar-ok', x, y: base - okH, width: barW, height: okH, rx: Math.min(4, barW / 3) }));
      if (badH > 0) group.append(svg('rect', { class: 'bar-bad', x, y: base - okH - badH, width: barW, height: badH, rx: Math.min(4, barW / 3) }));
      root.append(group);
      const hit = svg('rect', { class: 'hit', x: pad.left + slot * index, y: pad.top, width: slot, height: plotH });
      hit.addEventListener('mouseenter', () => showTip(group.firstChild || hit, row));
      hit.addEventListener('mouseleave', hideTip);
      hit.addEventListener('touchstart', () => showTip(group.firstChild || hit, row), { passive: true });
      root.append(hit);
      if (index % labelEvery === 0 || index === n - 1) {
        root.append(svg('text', { class: 'axis-label', x: pad.left + slot * index + slot / 2, y: height - 8,
          'text-anchor': 'middle' }, dayLabel(row.day)));
      }
    });
    const empty = data.every((row) => !row.total);
    setChildren(wrap, root, empty ? h('div', { class: 'chart-empty' }, '这段时间还没有解析记录') : null);
  };

  if (window.ResizeObserver) {
    let frame = 0;
    new ResizeObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(draw); }).observe(wrap);
  }
  requestAnimationFrame(draw);
  wrap.addEventListener('mouseleave', hideTip);
  return wrap;
}

/** 横向占比条：rows [{label, value, total?}] */
export function hbars(rows) {
  const max = Math.max(1, ...rows.map((row) => row.value));
  return h('div', null, rows.map((row, index) => h('div', { class: 'hbar' },
    h('div', { class: 'ellipsis' }, row.label),
    h('div', { class: 'track' }, h('span', { style: { width: `${(row.value / max) * 100}%`, animationDelay: `${index * 80}ms` } })),
    h('div', { class: 'num' }, row.text || String(row.value)))));
}
