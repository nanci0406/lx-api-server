// LX API Server · 公开首页：服务状态、在线解析、获取音源脚本

import {
  h, icon, api, setChildren, toast, segmented, field, passwordInput, copyText, fmt, statusPill, themeButton, stagger,
  withLoading, emptyState,
} from './core.js';

const app = document.getElementById('app');
const LOGO = { tx: 'Q', kg: 'K', wy: '网' };

function moduleCard(m) {
  return h('div', { class: 'card module-card hover' },
    h('div', { class: `logo ${m.source}` }, LOGO[m.source] || m.source.slice(0, 1).toUpperCase()),
    h('div', { class: 'grow' }, h('div', { class: 'list-title' }, m.name),
      h('div', { class: 'list-sub ellipsis', title: m.detail || '' }, m.detail || `检查于 ${fmt.relative(m.checked_at)}`)),
    statusPill(m.status));
}

async function main() {
  const statusStrip = h('div', { class: 'status-strip' }, Array.from({ length: 3 }, () => h('div', { class: 'skeleton block', style: { height: '76px' } })));
  const resolveCard = h('section', { class: 'card' });
  const scriptCard = h('section', { class: 'card' });
  setChildren(app, h('div', { class: 'public' },
    h('nav', { class: 'public-nav' },
      h('a', { class: 'brand', href: '/' }, h('div', { class: 'brand-mark' }, icon('logo')),
        h('div', null, h('div', { class: 'brand-name' }, 'LX API Server'), h('div', { class: 'brand-sub' }, 'LX Music 音源服务'))),
      h('span', { class: 'spacer' }), themeButton(),
      h('a', { class: 'btn sm', href: '/admin' }, icon('lock'), '管理后台')),
    h('header', { class: 'hero' },
      h('h1', null, '多平台音乐解析，', h('span', { class: 'grad' }, '一个地址搞定')),
      h('p', null, '为 LX Music 提供 QQ 音乐、酷狗音乐、网易云音乐的播放链接解析。使用管理员分配的用户名和 Key 即可接入。')),
    statusStrip,
    h('div', { class: 'grid cols-2 public-grid' }, resolveCard, scriptCard),
    h('footer', { class: 'public-foot' }, '音乐平台不易，请尊重版权，支持正版。')));

  let status;
  try {
    status = await api('GET', '/api/public/status');
  } catch (e) {
    setChildren(statusStrip, h('div', { class: 'card' }, h('div', { class: 'card-body' }, h('div', { class: 'notice bad' }, icon('alert'),
      h('div', { class: 'grow' }, e.message), h('button', { class: 'btn sm', type: 'button', onclick: () => location.reload() }, icon('refresh'), '重试')))));
    resolveCard.classList.add('hidden');
    scriptCard.classList.add('hidden');
    return;
  }
  renderStatus(status);
  renderResolve(status);
  renderScript(status);

  setInterval(async () => {
    if (document.hidden) return;
    try { renderStatus(await api('GET', '/api/public/status'), false); } catch (e) { /* 忽略 */ }
  }, 60000);

  function renderStatus(data, animate = true) {
    if (!data.modules.length) {
      setChildren(statusStrip, h('div', { class: 'card' }, emptyState('pulse', '暂未获取到平台状态', '服务刚启动时需要几秒钟检查各平台')));
      return;
    }
    setChildren(statusStrip, data.modules.map(moduleCard));
    if (animate) stagger(statusStrip);
  }

  function renderResolve(data) {
    if (!data.sources.length) {
      setChildren(resolveCard, h('div', { class: 'card-body' }, emptyState('music', '没有可用的平台', '管理员还没有启用任何音乐平台')));
      return;
    }
    let source = data.sources[0].id;
    const username = h('input', { class: 'input', autocomplete: 'username', placeholder: '用户名', spellcheck: 'false', autocapitalize: 'off' });
    const key = passwordInput({ autocomplete: 'off', placeholder: '管理员分配给你的 Key' });
    const songId = h('input', { class: 'input mono', placeholder: '例如 0039MnYb0qxYhV', spellcheck: 'false', autocapitalize: 'off' });
    const quality = h('select', { class: 'select' });
    const result = h('div');
    const submit = h('button', { class: 'btn primary block lg', type: 'submit' }, icon('zap'), '获取下载链接');
    const fillQualities = () => {
      const qualities = data.sources.find((s) => s.id === source).qualities;
      quality.replaceChildren(...qualities.map((q) => h('option', { value: q }, q)));
    };
    fillQualities();
    const sourceTabs = segmented(data.sources.map((s) => [s.id, s.name]), source, (value) => { source = value; fillQualities(); }, { block: true });

    const form = h('form', { class: 'stack', novalidate: true },
      field({ label: '平台', control: sourceTabs }),
      data.key_required ? h('div', { class: 'grid cols-2 tight-grid' }, field({ label: '用户名', control: username }), field({ label: 'Key', control: key })) : null,
      h('div', { class: 'grid cols-2 tight-grid' },
        field({ label: '歌曲 ID', control: songId, help: '歌曲的 songmid / hash / id' }),
        field({ label: '音质', control: quality })),
      submit,
      result);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      setChildren(result);
      if (!songId.value.trim()) { setChildren(result, h('div', { class: 'field-error' }, '请输入歌曲 ID')); songId.focus(); return; }
      if (data.key_required && (!username.value.trim() || !key.input.value.trim())) {
        setChildren(result, h('div', { class: 'field-error' }, '请输入用户名和 Key'));
        return;
      }
      await withLoading(submit, async () => {
        try {
          const res = await api('POST', '/api/public/resolve', {
            source, song_id: songId.value.trim(), quality: quality.value, username: username.value.trim(), key: key.input.value.trim(),
          });
          setChildren(result, h('div', { class: 'result-box' },
            h('div', { class: 'row' }, h('div', { class: 'card-icon ok' }, icon('check')),
              h('div', { class: 'grow' }, h('div', { class: 'list-title' }, '链接已生成'),
                h('div', { class: 'list-sub' }, `音质 ${res.quality}${res.cached ? ' · 来自缓存' : ''}${res.expire_at ? ` · ${fmt.relative(res.expire_at)}失效` : ''}`))),
            h('div', { class: 'code-box' }, h('span', { class: 'value', title: res.url }, res.url),
              h('button', { class: 'icon-btn sm', type: 'button', 'aria-label': '复制链接', onclick: () => copyText(res.url, '链接') }, icon('copy'))),
            h('div', { class: 'row wrap' },
              h('a', { class: 'btn primary sm', href: res.url, target: '_blank', rel: 'noopener noreferrer' }, icon('download'), '打开 / 下载'),
              h('button', { class: 'btn sm', type: 'button', onclick: () => copyText(res.url, '链接') }, icon('copy'), '复制链接'))));
        } catch (e) {
          setChildren(result, h('div', { class: 'notice bad' }, icon('alert'), h('div', null, e.message)));
        }
      });
    });
    setChildren(resolveCard,
      h('div', { class: 'card-header' }, h('div', { class: 'card-icon' }, icon('zap')),
        h('div', { class: 'grow' }, h('h3', { class: 'card-title' }, '在线解析'), h('p', { class: 'card-sub' }, '获取单首歌曲的播放 / 下载链接'))),
      h('div', { class: 'card-body' }, form));
  }

  function renderScript(data) {
    const header = h('div', { class: 'card-header' }, h('div', { class: 'card-icon' }, icon('code')),
      h('div', { class: 'grow' }, h('h3', { class: 'card-title' }, '接入 LX Music'), h('p', { class: 'card-sub' }, '导入自定义音源脚本')));
    if (!data.script_enabled) {
      setChildren(scriptCard, header, h('div', { class: 'card-body' }, emptyState('code', '管理员没有开放脚本下载', '请向管理员索取音源脚本')));
      return;
    }
    const key = passwordInput({ autocomplete: 'off', placeholder: '你的 Key' });
    const output = h('div');
    const build = () => {
      const value = key.input.value.trim();
      if (!value) { setChildren(output); return; }
      const url = `${location.origin}/script?key=${encodeURIComponent(value)}`;
      setChildren(output, h('div', { class: 'stack' },
        h('div', { class: 'code-box' }, h('span', { class: 'value', title: url }, url),
          h('button', { class: 'icon-btn sm', type: 'button', 'aria-label': '复制脚本链接', onclick: () => copyText(url, '脚本链接') }, icon('copy'))),
        h('div', { class: 'row wrap' },
          h('button', { class: 'btn primary sm', type: 'button', onclick: () => copyText(url, '脚本链接') }, icon('copy'), '复制链接'),
          h('a', { class: 'btn sm', href: url, rel: 'noopener' }, icon('download'), '下载脚本文件'))));
    };
    key.input.addEventListener('input', build);
    setChildren(scriptCard, header, h('div', { class: 'card-body stack' },
      h('ol', { class: 'help-list steps-list' },
        h('li', null, '输入管理员分配给你的 Key，生成音源脚本链接'),
        h('li', null, '打开 LX Music →「设置」→「自定义源」→「在线导入」'),
        h('li', null, '粘贴链接并导入，然后在音源列表里选择它')),
      field({ label: 'Key', control: key }),
      output,
      h('div', { class: 'notice' }, icon('info'), h('div', null, 'Key 等同于你的账号密码，请不要分享给别人。'))));
  }
}

main().catch((e) => { console.error(e); toast(e.message || String(e), 'error'); });
