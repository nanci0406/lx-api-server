// QQ 音乐登录：QQ 扫码、微信扫码、手机验证码

import { h, icon, svg, api, setChildren, toast, segmented, switchControl, field, withLoading } from '../core.js';

const METHODS = [['qq', 'QQ 扫码', 'qr'], ['wx', '微信扫码', 'chat'], ['phone', '手机验证码', 'phone']];
const RING_R = 16;
const RING_C = 2 * Math.PI * RING_R;

export async function qqLoginPage(ctx) {
  let method = 'qq';
  let session = null;
  let pollTimer = null;
  let countdownTimer = null;
  let cooldownTimer = null;

  const stage = h('div', { class: 'qr-stage-wrap' });
  const side = h('div');
  const tabs = segmented(METHODS, method, (value) => { method = value; start(); }, { block: true });
  setChildren(ctx.container,
    h('div', { class: 'page-head' }, h('div', null, h('h2', null, 'QQ 音乐登录'),
      h('p', null, '扫码或用手机验证码登录 QQ 音乐，自动获取完整的登录凭证(含刷新所需的 refresh_key)，不需要再手动抓包'))),
    h('div', { class: 'grid cols-2 login-grid' },
      h('section', { class: 'card' }, h('div', { class: 'card-body stack' }, tabs, stage)),
      side));

  // ---------- 通用 ----------

  function stopTimers() {
    clearInterval(pollTimer);
    clearInterval(countdownTimer);
    pollTimer = countdownTimer = null;
  }

  function cancelCurrent() {
    stopTimers();
    if (session && !session.finished) {
      api('POST', `/api/admin/qqlogin/${encodeURIComponent(session.id)}/cancel`, {}).catch(() => {});
    }
    session = null;
  }
  ctx.onCleanup(() => { cancelCurrent(); clearInterval(cooldownTimer); });

  function renderHelp() {
    setChildren(side, h('section', { class: 'card' },
      h('div', { class: 'card-header' }, h('div', { class: 'card-icon' }, icon('info')), h('h3', { class: 'card-title' }, '说明')),
      h('div', { class: 'card-body' }, h('ul', { class: 'help-list' },
        h('li', null, '登录得到的凭证只在服务器内存里保留 10 分钟，点击「保存到配置」后才会写入配置文件。'),
        h('li', null, '可以保存为主账号，也可以加入账号池(cookie 池)；同一个 QQ 号再次加入会覆盖旧凭证。'),
        h('li', null, '勾选「自动刷新登录」后，服务会定时续期，不需要再定期手动更新 key。'),
        h('li', null, '手机验证码登录可能需要先完成一次人机验证，页面会给出验证链接。'),
        h('li', null, '暂不支持「手机 QQ 音乐客户端扫码」的登录方式。')))));
  }

  function start() {
    cancelCurrent();
    renderHelp();
    if (method === 'phone') renderPhone();
    else startQr(method);
  }

  // ---------- 扫码 ----------

  function steps(current) {
    const order = ['scan', 'conf', 'done'];
    const labels = ['扫描二维码', '在手机上确认', '登录成功'];
    const index = order.indexOf(current);
    const nodes = [];
    labels.forEach((label, i) => {
      if (i) nodes.push(h('div', { class: ['step-line', i <= index && 'done'] }, h('span')));
      nodes.push(h('div', { class: ['step', i === index && 'on', i < index && 'done'] },
        h('span', { class: 'num' }, i < index ? icon('check') : String(i + 1)), h('span', { class: 'txt' }, label)));
    });
    return h('div', { class: 'steps' }, nodes);
  }

  async function startQr(kind) {
    setChildren(stage, h('div', { class: 'qr-stage' }, h('div', { class: 'qr-frame' }, h('div', { class: 'skeleton', style: { height: '100%' } })),
      h('p', { class: 'muted' }, '正在获取二维码…')));
    let data;
    try {
      data = await api('POST', '/api/admin/qqlogin/qr', { kind });
    } catch (e) {
      if (!ctx.alive() || method !== kind) return;
      setChildren(stage, qrError(e.message, kind));
      return;
    }
    if (!ctx.alive() || method !== kind) {
      api('POST', `/api/admin/qqlogin/${encodeURIComponent(data.id)}/cancel`, {}).catch(() => {});
      return;
    }
    session = { id: data.id, kind, finished: false };
    const thisSession = session;
    const img = h('img', { src: data.image, alt: kind === 'qq' ? 'QQ 登录二维码' : '微信登录二维码' });
    const fg = svg('circle', { class: 'fg', cx: 20, cy: 20, r: RING_R, 'stroke-dasharray': RING_C, 'stroke-dashoffset': 0 });
    const ringText = svg('text', { x: 20, y: 20 }, String(data.expires_in));
    const ring = svg('svg', { class: 'qr-ring', viewBox: '0 0 40 40' }, svg('circle', { class: 'bg', cx: 20, cy: 20, r: RING_R }), fg, ringText);
    const frame = h('div', { class: ['qr-frame', kind] }, img, ring);
    const statusText = h('p', { class: 'qr-status' }, kind === 'qq' ? '请用手机 QQ 扫描二维码' : '请用微信扫描二维码');
    const stepsHolder = h('div', { class: 'steps-holder' }, steps('scan'));
    setChildren(stage, h('div', { class: 'qr-stage' }, frame, stepsHolder, statusText));

    const deadline = Date.now() + data.expires_in * 1000;
    countdownTimer = setInterval(() => {
      const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
      fg.setAttribute('stroke-dashoffset', String(RING_C * (1 - left / data.expires_in)));
      ringText.textContent = String(left);
      if (!left) clearInterval(countdownTimer);
    }, 1000);

    const cover = (iconName, kindClass, text, retry) => {
      ring.remove();
      frame.appendChild(h('div', { class: 'qr-cover' }, h('div', { class: 'inner' },
        h('div', { class: ['big', kindClass] }, icon(iconName)), h('div', null, text),
        retry ? h('button', { class: 'btn primary sm', onclick: () => start() }, icon('refresh'), '重新获取') : null)));
    };

    let polling = false;
    let failures = 0;
    const poll = async () => {
      // 网络慢时上一次查询可能还没返回，不重叠查询，也不重复处理已结束的会话
      if (session !== thisSession || thisSession.finished || polling) return;
      polling = true;
      let info;
      try {
        info = await api('GET', `/api/admin/qqlogin/${encodeURIComponent(thisSession.id)}`);
      } catch (e) {
        if (session !== thisSession || thisSession.finished) return;
        failures += 1;
        if (e.status !== 404 && failures < 3) return; // 偶尔的网络错误：下一轮再查
        stopTimers();
        thisSession.finished = true;
        cover('alert', 'warn', e.status === 404 ? '登录会话已过期' : e.message, true);
        return;
      } finally {
        polling = false;
      }
      if (session !== thisSession || thisSession.finished) return;
      failures = 0;
      if (info.state === 'scan' || info.state === 'conf') {
        setChildren(stepsHolder, steps(info.state));
        statusText.textContent = info.state === 'conf' ? '已扫码，请在手机上确认登录' : (kind === 'qq' ? '请用手机 QQ 扫描二维码' : '请用微信扫描二维码');
        return;
      }
      stopTimers();
      thisSession.finished = true;
      if (info.state === 'done') {
        setChildren(stepsHolder, steps('done'));
        statusText.textContent = '登录成功，请在旁边选择保存位置';
        cover('check', '', '登录成功', false);
        showResult(info);
      } else if (info.state === 'timeout') {
        statusText.textContent = '二维码已过期';
        cover('clock', 'warn', '二维码已失效', true);
      } else if (info.state === 'refuse') {
        statusText.textContent = '你在手机上拒绝了登录';
        cover('x', 'warn', '已拒绝登录', true);
      } else {
        statusText.textContent = info.message || '登录失败';
        cover('alert', 'warn', info.message || '登录失败', true);
      }
    };
    pollTimer = setInterval(poll, 2000);
  }

  function qrError(message, kind) {
    return h('div', { class: 'qr-stage' }, h('div', { class: 'empty' }, h('div', { class: 'empty-icon' }, icon('alert')),
      h('div', { class: 'empty-title' }, '获取二维码失败'), h('div', null, message),
      h('button', { class: 'btn primary', onclick: () => startQr(kind) }, icon('refresh'), '重试')));
  }

  // ---------- 手机验证码 ----------

  function renderPhone() {
    const country = h('input', { class: 'input', value: '86', inputmode: 'numeric', maxlength: 4, 'aria-label': '国家/地区区号' });
    const phone = h('input', { class: 'input', inputmode: 'numeric', autocomplete: 'tel-national', placeholder: '手机号', maxlength: 15 });
    const code = h('input', { class: 'input', inputmode: 'numeric', autocomplete: 'one-time-code', placeholder: '短信验证码', maxlength: 8 });
    const sendButton = h('button', { class: 'btn', type: 'button' }, '发送验证码');
    const loginButton = h('button', { class: 'btn primary block lg', type: 'submit' }, '登录');
    const hint = h('div');

    const cooldown = (seconds) => {
      clearInterval(cooldownTimer);
      let left = seconds;
      sendButton.disabled = true;
      sendButton.textContent = `${left} 秒后重发`;
      cooldownTimer = setInterval(() => {
        left -= 1;
        if (left <= 0) {
          clearInterval(cooldownTimer);
          sendButton.disabled = false;
          sendButton.textContent = '重新发送';
        } else {
          sendButton.textContent = `${left} 秒后重发`;
        }
      }, 1000);
    };

    sendButton.addEventListener('click', async () => {
      if (!/^\d{5,15}$/.test(phone.value.trim())) { setChildren(hint, h('div', { class: 'field-error' }, '请输入正确的手机号')); phone.focus(); return; }
      setChildren(hint);
      sendButton.disabled = true;
      sendButton.textContent = '发送中…';
      try {
        const data = await api('POST', '/api/admin/qqlogin/phone/send', { phone: phone.value.trim(), country_code: country.value.trim() });
        if (data.state === 'sent') {
          toast('验证码已发送', 'success');
          cooldown(data.cooldown || 60);
          code.focus();
          return;
        }
        sendButton.disabled = false;
        sendButton.textContent = '发送验证码';
        if (data.state === 'captcha') {
          setChildren(hint, h('div', { class: 'notice warn' }, icon('shield'), h('div', { class: 'stack tight' },
            h('div', null, '需要先完成一次人机验证，完成后再点「发送验证码」。'),
            data.url ? h('a', { class: 'btn sm', href: data.url, target: '_blank', rel: 'noopener noreferrer' }, icon('external'), '打开验证页面')
              : h('div', { class: 'faint' }, '服务端没有返回验证地址，请稍后重试'))));
        } else {
          setChildren(hint, h('div', { class: 'notice warn' }, icon('clock'), h('div', null, '发送太频繁，请稍后再试')));
        }
      } catch (e) {
        sendButton.disabled = false;
        sendButton.textContent = '发送验证码';
        setChildren(hint, h('div', { class: 'notice bad' }, icon('alert'), h('div', null, e.message)));
      }
    });

    const form = h('form', { class: 'stack phone-form', novalidate: true },
      h('div', { class: 'phone-row' },
        field({ label: '区号', control: h('div', { class: 'input-affix prefix' }, h('span', { class: 'affix' }, '+'), country) }),
        field({ label: '手机号', control: phone })),
      field({ label: '验证码', control: h('div', { class: 'code-row' }, code, sendButton) }),
      hint,
      loginButton);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (!/^\d{4,8}$/.test(code.value.trim())) { setChildren(hint, h('div', { class: 'field-error' }, '请输入短信里的验证码')); code.focus(); return; }
      await withLoading(loginButton, async () => {
        try {
          const info = await api('POST', '/api/admin/qqlogin/phone/verify',
            { phone: phone.value.trim(), code: code.value.trim(), country_code: country.value.trim() });
          session = { id: info.id, kind: 'phone', finished: true };
          setChildren(hint, h('div', { class: 'notice ok' }, icon('checkCircle'), h('div', null, '登录成功，请选择保存位置')));
          showResult(info);
        } catch (e) {
          setChildren(hint, h('div', { class: 'notice bad' }, icon('alert'), h('div', null, e.message)));
        }
      });
    });
    setChildren(stage, form);
    setTimeout(() => phone.focus(), 60);
  }

  // ---------- 结果与保存 ----------

  function showResult(info) {
    const account = info.account || {};
    let target = ctx.me.cookiepool ? 'pool' : 'main';
    let enableRefresh = true;
    const choices = h('div', { class: 'choice-cards' });
    const renderChoices = () => choices.replaceChildren(...[
      ['main', '主账号', '写入 module.tx.user，替换当前的主账号'],
      ['pool', '加入账号池', '加入 module.cookiepool.tx，同一个 QQ 号会被更新'],
    ].map(([value, title, desc]) => h('label', { class: ['choice', target === value && 'on'] },
      h('input', { type: 'radio', name: 'target', value, checked: target === value, onchange: () => { target = value; renderChoices(); } }),
      h('span', { class: 'title' }, title), h('span', { class: 'desc' }, desc))));
    renderChoices();
    const saveButton = h('button', { class: 'btn primary block lg' }, icon('check'), '保存到配置');
    const card = h('section', { class: 'card result-card' }, h('div', { class: 'card-body stack' },
      h('div', { class: 'success-burst' }, icon('check')),
      h('h3', { class: 'center-title' }, '登录成功'),
      h('div', { class: 'row account-row' }, h('div', { class: 'avatar lg' }, (account.nick || account.uin || '?').slice(0, 1)),
        h('div', { class: 'grow' }, h('div', { class: 'list-title' }, account.nick || 'QQ 音乐账号'),
          h('div', { class: 'list-sub mono' }, `uin ${account.uin || '-'}`))),
      account.has_refresh ? null : h('div', { class: 'notice warn' }, icon('alert'),
        h('div', null, '这次登录没有返回 refresh 凭证，自动刷新登录可能无法续期。')),
      h('div', { class: 'field-label' }, '保存位置'),
      choices,
      h('div', { class: 'faint' }, ctx.me.cookiepool ? '当前为账号池模式，主账号配置不会被使用。' : '当前为单账号模式；加入账号池后需要在配置里开启账号池才会使用。'),
      switchControl({ checked: true, label: '同时开启这个账号的自动刷新登录', onChange: (checked) => { enableRefresh = checked; } }),
      saveButton));
    saveButton.addEventListener('click', () => withLoading(saveButton, async () => {
      try {
        const data = await api('POST', `/api/admin/qqlogin/${encodeURIComponent(info.id)}/apply`, { target, enable_refresh: enableRefresh });
        if (data.reload_error) toast(`已保存，但热重载失败：${data.reload_error}`, 'error', 9000);
        else toast('已保存到配置', 'success');
        setChildren(side, h('section', { class: 'card result-card' }, h('div', { class: 'card-body stack' },
          h('div', { class: 'success-burst' }, icon('check')),
          h('h3', { class: 'center-title' }, '已保存'),
          h('p', { class: 'muted center' }, data.note),
          h('div', { class: 'row wrap center-row' },
            h('a', { class: 'btn', href: '/admin/health', 'data-link': true }, icon('pulse'), '查看模块状态'),
            h('button', { class: 'btn primary', onclick: () => start() }, icon('plus'), '再登录一个')))));
        ctx.refreshBadges();
      } catch (e) {
        toast(e.message, 'error');
      }
    }));
    setChildren(side, card);
    if (window.innerWidth <= 960) setTimeout(() => card.scrollIntoView({ behavior: 'smooth', block: 'start' }), 200);
  }

  start();
}
