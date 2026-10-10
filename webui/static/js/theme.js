// 在页面渲染前确定主题，避免先闪一下浅色再变成深色
(function () {
  var stored = 'auto';
  try { stored = localStorage.getItem('lx-theme') || 'auto'; } catch (e) {}
  var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  function apply(mode) {
    var dark = mode === 'dark' || (mode === 'auto' && media && media.matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) { meta.setAttribute('content', dark ? '#0c0e19' : '#f3f4fa'); }
  }
  apply(stored);
  window.__lxTheme = {
    get: function () { try { return localStorage.getItem('lx-theme') || 'auto'; } catch (e) { return 'auto'; } },
    set: function (mode) { try { localStorage.setItem('lx-theme', mode); } catch (e) {} apply(mode); },
    apply: apply
  };
  if (media && media.addEventListener) {
    media.addEventListener('change', function () { if (window.__lxTheme.get() === 'auto') { apply('auto'); } });
  }
})();
