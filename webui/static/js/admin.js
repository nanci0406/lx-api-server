// LX API Server · 管理后台：外壳布局、路由、登录

import {
  h, icon, setChildren, api, onUnauthorized, toast, confirmDialog, passwordInput, field, themeButton,
  withLoading,
} from './core.js';
import { dashboardPage } from './pages/dashboard.js';
import { configPage } from './pages/config.js';
import { usersPage } from './pages/users.js';
import { statsPage } from './pages/stats.js';
import { healthPage } from './pages/health.js';
import { musicLoginPage } from './pages/musiclogin.js';
import { accountPage } from './pages/account.js';

const NAV = [
  { section: '总览' },
  { path: '/admin', label: '概览', icon: 'home', page: dashboardPage, bottom: true },
  { section: '管理' },
  { path: '/admin/config', label: '配置', icon: 'sliders', page: configPage, bottom: true },
  { path: '/admin/users', label: '用户', icon: 'users', page: usersPage, bottom: true },
  { path: '/admin/stats', label: '统计', icon: 'chart', page: statsPage, bottom: true },
  { path: '/admin/health', label: '模块状态', icon: 'pulse', page: healthPage, badge: 'health' },
  { section: '账号' },
  { path: '/admin/music-login', label: '音乐账号', icon: 'qr', page: musicLoginPage },
  { path: '/admin/account', label: '账号安全', icon: 'shield', page: accountPage },
];
const ROUTES = NAV.filter((item) => item.path);
// 改过名的页面：旧地址自动跳到新地址
const ALIASES = { '/admin/qqlogin': '/admin/music-login' };

const app = document.getElementById('app');
const state = { me: null, page: null, guard: null, shell: null, renderToken: 0 };

// ---------------------------------------------------------------------------
// 启动
// ---------------------------------------------------------------------------

onUnauthorized(() => {
  if (!state.me) return;
  state.me = null;
  state.guard = null;
  cleanupPage(); // 停掉页面上的定时刷新
  toast('登录已过期，请重新登录', 'warn');
  renderLogin();
});

async function boot() {
  try {
    state.me = await api('GET', '/api/admin/me');
  } catch (e) {
    if (e.status !== 401) toast(e.message, 'error');
    renderLogin();
    return;
  }
  renderShell();
  route(location.pathname);
}

// ---------------------------------------------------------------------------
// 登录页
// ---------------------------------------------------------------------------

function renderLogin() {
  document.title = '登录 · LX API Server';
  if (location.pathname !== '/admin/login') {
    sessionStorageSet('lx-after-login', location.pathname + location.search + location.hash);
    history.replaceState(null, '', '/admin/login');
  }
  const username = h('input', { class: 'input', name: 'username', autocomplete: 'username', placeholder: '管理员用户名',
    spellcheck: 'false', autocapitalize: 'off' });
  const password = passwordInput({ name: 'password', autocomplete: 'current-password', placeholder: '密码' });
  const error = h('div', { class: 'field-error', role: 'alert' });
  const submit = h('button', { class: 'btn primary lg block', type: 'submit' }, '登录');
  const panel = h('div', { class: 'auth-panel stack' },
    field({ label: '用户名', control: username }),
    field({ label: '密码', control: password }),
    error,
    submit);
  const card = h('form', { class: 'auth-card', novalidate: true },
    h('div', { class: 'brand-mark' }, icon('logo')),
    h('h1', null, '欢迎回来'),
    h('p', { class: 'sub' }, '登录 LX API Server 管理后台'),
    panel,
    h('div', { class: 'auth-foot' }, h('a', { href: '/' }, '← 返回首页')));

  card.addEventListener('submit', async (event) => {
    event.preventDefault();
    error.textContent = '';
    if (!username.value.trim() || !password.input.value) {
      error.textContent = '请输入用户名和密码';
      shake(panel);
      return;
    }
    await withLoading(submit, async () => {
      try {
        await api('POST', '/api/admin/login', { username: username.value.trim(), password: password.input.value });
        state.me = await api('GET', '/api/admin/me');
        const next = sessionStorageGet('lx-after-login');
        sessionStorageSet('lx-after-login', '');
        renderShell();
        const target = next && next.startsWith('/admin') && !next.startsWith('/admin/login') ? next : '/admin';
        history.replaceState(null, '', target);
        route(new URL(target, location.origin).pathname);
        toast(`欢迎回来，${state.me.username}`, 'success', 2500);
      } catch (e) {
        error.textContent = e.message;
        password.input.select();
        shake(panel);
      }
    });
  });

  setChildren(app,
    h('div', { class: 'auth' },
      h('div', { class: 'auth-theme' }, themeButton()),
      card));
  state.shell = null;
  setTimeout(() => (username.value ? password.input : username).focus(), 80);
}

function shake(el) {
  el.classList.remove('shake');
  void el.offsetWidth;
  el.classList.add('shake');
}

function sessionStorageGet(key) { try { return sessionStorage.getItem(key); } catch (e) { return null; } }
function sessionStorageSet(key, value) { try { sessionStorage.setItem(key, value); } catch (e) { /* 忽略 */ } }

// ---------------------------------------------------------------------------
// 外壳：侧边栏、顶栏、底部导航
// ---------------------------------------------------------------------------

function renderShell() {
  const navLinks = {};
  const nav = h('nav', { class: 'nav', 'aria-label': '主导航' },
    NAV.map((item) => {
      if (item.section) return h('div', { class: 'nav-section' }, item.section);
      const link = h('a', { class: 'nav-item', href: item.path, 'data-link': true }, icon(item.icon), h('span', null, item.label));
      navLinks[item.path] = link;
      return link;
    }));
  const avatar = h('div', { class: 'avatar' }, state.me.username.slice(0, 1));
  const sidebar = h('aside', { class: 'sidebar' },
    h('a', { class: 'brand', href: '/admin', 'data-link': true },
      h('div', { class: 'brand-mark' }, icon('logo')),
      h('div', null, h('div', { class: 'brand-name' }, 'LX API Server'), h('div', { class: 'brand-sub' }, '管理后台'))),
    nav,
    h('div', { class: 'sidebar-foot' },
      h('div', { class: 'user-chip' }, avatar,
        h('div', { class: 'grow' }, h('div', { class: 'name ellipsis' }, state.me.username), h('div', { class: 'role' }, '管理员')),
        themeButton(),
        h('button', { class: 'icon-btn', title: '退出登录', 'aria-label': '退出登录', onclick: logout }, icon('logout')))));

  const title = h('h1', { class: 'topbar-title' });
  const topbar = h('header', { class: 'topbar' },
    h('button', { class: 'icon-btn menu-btn', 'aria-label': '打开菜单', onclick: () => toggleDrawer(true) }, icon('menu')),
    title,
    h('div', { class: 'topbar-actions' }, h('a', { class: 'btn ghost sm', href: '/', target: '_blank', rel: 'noopener' },
      icon('external'), '首页')));

  const bottomLinks = {};
  const bottom = h('nav', { class: 'bottom-nav', 'aria-label': '快捷导航' },
    ROUTES.filter((item) => item.bottom).map((item) => {
      const link = h('a', { href: item.path, 'data-link': true }, icon(item.icon), h('span', null, item.label));
      bottomLinks[item.path] = link;
      return link;
    }),
    h('button', { type: 'button', onclick: () => toggleDrawer(true) }, icon('menu'), h('span', null, '更多')));

  const content = h('main', { class: 'content', id: 'content' });
  const shell = h('div', { class: 'shell' },
    sidebar,
    h('div', { class: 'scrim', onclick: () => toggleDrawer(false) }),
    h('div', { class: 'main' }, topbar, content),
    bottom);
  setChildren(app, shell);
  state.shell = { shell, content, title, topbar, navLinks, bottomLinks, avatar };

  if (scrollHandler) window.removeEventListener('scroll', scrollHandler);
  scrollHandler = () => topbar.classList.toggle('scrolled', window.scrollY > 56);
  window.addEventListener('scroll', scrollHandler, { passive: true });
  refreshBadges();
}

let scrollHandler = null;

function toggleDrawer(open) {
  if (state.shell) state.shell.shell.classList.toggle('drawer-open', open);
}

async function logout() {
  if (!(await confirmDialog({ title: '退出登录', message: '确定要退出管理后台吗？', confirmText: '退出' }))) return;
  try { await api('POST', '/api/admin/logout'); } catch (e) { /* 会话可能已经失效 */ }
  state.me = null;
  state.guard = null;
  cleanupPage();
  toast('已退出登录', 'success', 2000);
  renderLogin();
}

let badgeTimer = null;
async function refreshBadges() {
  clearTimeout(badgeTimer);
  if (!state.me || !state.shell) return;
  try {
    const data = await api('GET', '/api/admin/health');
    const issues = data.modules.filter((m) => m.status !== 'healthy' && m.status !== 'disabled').length +
      data.tasks.filter((t) => t.consecutive_failures).length;
    const link = state.shell.navLinks['/admin/health'];
    const existing = link.querySelector('.badge');
    if (existing) existing.remove();
    if (issues) link.appendChild(h('span', { class: 'badge', title: `${issues} 项需要关注` }, issues));
  } catch (e) { /* 角标失败不影响使用 */ }
  badgeTimer = setTimeout(refreshBadges, 60000);
}

// ---------------------------------------------------------------------------
// 路由
// ---------------------------------------------------------------------------

function findRoute(path) {
  const clean = path.replace(/\/+$/, '') || '/admin';
  return ROUTES.find((item) => item.path === (ALIASES[clean] || clean)) || null;
}

async function canLeave() {
  if (!state.guard) return true;
  const message = state.guard();
  if (!message) return true;
  return confirmDialog({ title: '还有未保存的修改', message, confirmText: '放弃修改并离开', danger: true });
}

export async function navigate(target, { replace = false } = {}) {
  const url = new URL(target, location.origin);
  if (url.pathname + url.search === location.pathname + location.search && !url.hash) return;
  if (!(await canLeave())) return;
  state.guard = null;
  history[replace ? 'replaceState' : 'pushState'](null, '', url.pathname + url.search + url.hash);
  route(url.pathname);
}

function cleanupPage() {
  if (state.page) {
    for (const fn of state.page.cleanups) {
      try { fn(); } catch (e) { /* 忽略 */ }
    }
  }
  state.page = null;
}

function route(path) {
  if (!state.shell) return;
  let item = findRoute(path);
  if (!item) {
    item = ROUTES[0];
    history.replaceState(null, '', item.path);
  } else if (item.path !== (path.replace(/\/+$/, '') || '/admin')) {
    history.replaceState(null, '', item.path + location.search + location.hash); // 旧地址换成新地址
  }
  cleanupPage();
  toggleDrawer(false);
  const { content, title, navLinks, bottomLinks } = state.shell;
  for (const [p, link] of Object.entries(navLinks)) link.classList.toggle('active', p === item.path);
  for (const [p, link] of Object.entries(bottomLinks)) link.classList.toggle('active', p === item.path);
  title.textContent = item.label;
  document.title = `${item.label} · LX API Server`;

  const token = ++state.renderToken;
  const page = { cleanups: [], token };
  state.page = page;
  const container = h('div', { class: 'page-enter' });
  setChildren(content, container);
  window.scrollTo(0, 0);

  const ctx = {
    container,
    me: state.me,
    navigate,
    query: new URLSearchParams(location.search),
    hash: location.hash.slice(1),
    alive: () => state.page === page,
    onCleanup: (fn) => page.cleanups.push(fn),
    every(fn, ms) {
      // 页面在前台时才定时刷新
      const timer = setInterval(() => { if (!document.hidden && state.page === page) fn(); }, ms);
      page.cleanups.push(() => clearInterval(timer));
    },
    setGuard: (fn) => { if (state.page === page) state.guard = fn; },
    refreshBadges,
    setMe: (me) => { state.me = me; ctx.me = me; },
  };
  Promise.resolve(item.page(ctx)).catch((e) => {
    if (state.page !== page) return;
    if (e && e.status === 401) return;
    console.error(e);
    setChildren(container, h('div', { class: 'card' }, h('div', { class: 'card-body' },
      h('div', { class: 'notice bad' }, icon('alert'), h('div', null, '页面加载失败：', e.message || String(e))),
      h('div', { class: 'section-gap' }),
      h('button', { class: 'btn', onclick: () => route(location.pathname) }, icon('refresh'), '重试'))));
  });
}

document.addEventListener('click', (event) => {
  const link = event.target.closest('a[data-link]');
  if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const url = new URL(link.href, location.origin);
  if (url.origin !== location.origin) return;
  event.preventDefault();
  navigate(url.pathname + url.search + url.hash);
});

let restoringHistory = false;
window.addEventListener('popstate', async () => {
  if (restoringHistory) { restoringHistory = false; return; }
  if (!state.me) return;
  const target = location.pathname + location.search + location.hash;
  if (state.guard && state.guard()) {
    // 浏览器已经切换了地址，先回到原页面，确认后再离开
    restoringHistory = true;
    history.forward();
    if (await canLeave()) {
      state.guard = null;
      history.pushState(null, '', target);
      route(new URL(target, location.origin).pathname);
    }
    return;
  }
  route(location.pathname);
});

window.addEventListener('beforeunload', (event) => {
  if (state.guard && state.guard()) {
    event.preventDefault();
    event.returnValue = '';
  }
});

window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') toggleDrawer(false);
});

boot();
