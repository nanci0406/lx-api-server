# lx-api-server

基于 `lx-music-api-server` 改造的多音源解析服务，当前分支将 API 鉴权调整为 SQLite 用户 + Key 模式，并加入 Web 管理后台、解析统计、模块健康检查和登录保活任务。

## 功能概览

- 支持酷狗、QQ 音乐、网易云音源解析（咪咕、酷我已移除）。
- 使用 `X-Request-User` 和 `X-Request-Key` 做 API 请求鉴权。
- 提供 Web 管理后台（同时适配电脑和手机，支持浅色/深色主题），可管理配置、API 用户、解析统计、模块状态、QQ 音乐登录和管理员账号；公开首页可查看服务状态、在线解析单曲、生成音源脚本链接。
- 支持普通单账号模式和 cookie 池模式。
- 支持 QQ 音乐、酷狗、网易云的自动刷新登录/保活任务。
- 首次启动会自动生成默认配置和 SQLite 数据库。

## 环境要求

- Python 3.8+
- pip

安装依赖：

```bash
pip install -r requirements.txt
```

## 启动服务

```bash
python main.py
```

默认监听：

```text
http://0.0.0.0:9763
```

首次启动会生成：

- `config/config.yml`：主配置文件
- `config/data.db`：运行数据
- `cache.db`：请求缓存
- `app.db`：用户、管理员、解析日志和模块健康状态

如果仓库目录中存在旧版 `users.db`，启动时会自动迁移旧用户到 `app.db`。

## 管理后台

访问：

```text
http://127.0.0.1:9763/admin
```

默认管理员：

- 用户名：`admin`
- 密码：首次启动时随机生成，并打印在启动日志中

也可以通过环境变量指定初始管理员：

```bash
LX_ADMIN_USERNAME=admin LX_ADMIN_PASSWORD=your-password python main.py
```

后台包含：

- 概览（`/admin`）：今日/近 7 天解析、成功率、趋势图、平台状态、最近解析、定时任务是否正常
- 配置（`/admin/config`）：按分组编辑常用配置，带校验；从属项（如代理地址）在对应开关关闭时会变灰提示；密钥类字段只显示“已设置/末尾几位”。修改后点“保存并生效”即热重载，标有“需重启”的项目要重启服务。“原始配置”页可以直接编辑整个 `config.yml`（保存前自动备份为 `config/config.yml.bak`，新配置无法加载时自动恢复）
- 用户（`/admin/users`）：新建/停用/删除用户、重置 Key、复制音源脚本链接，查看每位用户的解析次数和成功率
- 统计（`/admin/stats`）：今天/近 7 天/近 30 天的趋势、平台分布、用户排行，解析记录可按用户/平台/结果筛选
- 模块状态（`/admin/health`）：各平台状态、定时任务（刷新登录、签到、清理记录）的执行情况，可以立即检查、立即执行任务
- 音乐账号（`/admin/music-login`，旧地址 `/admin/qqlogin` 会自动跳转）：扫码登录 QQ 音乐和网易云音乐，见下文“音乐账号登录”
- 账号安全（`/admin/account`）：修改管理员密码、退出其他设备上的登录

后台是单页应用，前端只调用 `/api/admin/*` JSON 接口；不依赖任何外部 CDN，可以在内网离线使用。

## API 鉴权

开启 `security.key.enable` 后，请求需要携带：

```http
X-Request-User: 用户名
X-Request-Key: 用户 Key
```

示例：

```bash
curl \
  -H "X-Request-User: demo" \
  -H "X-Request-Key: your-api-key" \
  "http://127.0.0.1:9763/url/tx/0039MnYb0qxYhV/128k"
```

常见 API 路径：

```text
/{method}/{source}/{songId}/{quality}
/{method}/{source}/{songId}
/local/{type}
/script
```

示例：

```text
/url/tx/{songId}/128k
/url/kg/{songId}/flac
/lyric/wy/{songId}
```

## 自动刷新登录

自动刷新任务由 `common.scheduler` 统一调度。服务启动时会按当前配置显式注册刷新任务，启动日志会打印已加载的任务列表。

非 cookie 池模式下，QQ 音乐刷新登录配置：

```yaml
module:
  tx:
    user:
      qqmusic_key: ""
      uin: ""
      refresh_login:
        enable: true
        interval: 86000
```

cookie 池模式下，QQ 音乐刷新登录配置：

```yaml
common:
  cookiepool: true

module:
  cookiepool:
    tx:
      - qqmusic_key: ""
        uin: ""
        refresh_login:
          enable: true
          interval: 86000
```

QQ 音乐刷新登录时会带上并保存完整的登录凭证。除 `qqmusic_key`、`uin` 外，登录时返回的 `refresh_key`、`refresh_token`、`openid`、`access_token`、`unionid` 也可以一并填写（没有的留空即可），刷新成功后程序会把响应里返回的新值自动写回配置。手动更换 `qqmusic_key` 时请同时更新这些字段，否则会用旧凭证去刷新。

```yaml
module:
  tx:
    user:
      qqmusic_key: ""
      uin: ""
      refresh_key: ""
      refresh_token: ""
      openid: ""
      access_token: ""
      unionid: ""
```

网易云刷新登录成功后，服务端返回的新登录 cookie（`MUSIC_U` 等）会合并写回配置里的 cookie（其余字段保持不变）；酷狗会写回新的 `userid` 和 `token`。

网易云的刷新请求参照 [NeteaseCloudMusicApi](https://www.npmjs.com/package/NeteaseCloudMusicApi) 的 `login_refresh`：走 `https://interface.music.163.com/eapi/login/token/refresh`，cookie 里没有 `os`、`appver`、`deviceId` 等客户端信息时按 PC 客户端补齐（从浏览器复制的 cookie 就属于这种情况）。刷新返回 `301` 表示 `MUSIC_U` 已经失效，刷新救不回来，需要到后台“音乐账号”页重新扫码登录。

刷新登录用哪种请求，优先看配置里的 `login_type`（1 微信、2 QQ，通过后台“音乐账号”页登录时会自动保存），没有时才按 `qqmusic_key` 的前缀（`W_X` 微信、`Q_H_L` QQ）判断，两者都不是则走通用的刷新接口。手动配置的账号不用填 `login_type`。

刷新失败（请求出错、返回非 0 业务码等）不会干等一个完整周期，而是按 1 分钟、5 分钟、30 分钟、2 小时的间隔退避重试（不超过任务自身的刷新间隔），成功后恢复正常周期。连续失败的任务会在后台“模块状态”页的“定时任务状态”里显示，对应模块也会标记为“降级”。

启动后可通过日志确认任务是否注册（`parse_logs_cleanup` 是解析记录的定时清理任务，与登录无关）：

```text
scheduler loaded 2 task(s): qqmusic_refresh_login, parse_logs_cleanup
```

cookie 池模式示例：

```text
scheduler loaded 2 task(s): qqmusic_refresh_login_pooled_0, parse_logs_cleanup
```

如果日志中没有 QQ 音乐刷新任务，请优先检查：

- `common.cookiepool` 是否符合当前使用模式
- `module.tx.user.refresh_login.enable`
- `module.cookiepool.tx[*].refresh_login.enable`
- `module.tx.user.qqmusic_key` 或 `module.cookiepool.tx[*].qqmusic_key`

## 配置热重载

后台保存配置（表单或原始配置）后会立即热重载配置并重建定时任务。刷新登录任务会按最新配置重新注册，cookie 池账号会在任务执行时读取当前配置，避免继续使用启动时的旧 token/key/session。

## 音乐账号登录

后台“音乐账号”页（`/admin/music-login`）可以登录 QQ 音乐和网易云音乐，登录后选择保存为主账号或加入 cookie 池，并可同时开启自动刷新登录。保存后配置会自动热重载，刷新任务立即生效。

### 网易云音乐

用网易云音乐 App 的“扫一扫”扫描页面上的二维码并确认即可（流程参照 NeteaseCloudMusicApi 的 `login_qr_key` / `login_qr_check`）。登录成功后网易云下发的 `MUSIC_U`、`__csrf` 等 cookie 会连同这次登录使用的客户端信息（`os`、`appver`、`deviceId` 等）一起保存到 `module.wy.user.cookie`（或 `module.cookiepool.wy`，同一个账号再次加入会按用户 ID 覆盖）。之后的解析和刷新登录都沿用这台“设备”。

二维码在服务端生成，需要安装依赖 `qrcode`（已写进 `requirements.txt`，升级后请重新执行 `pip install -r requirements.txt`）。如果网易云返回需要安全验证（风控），页面会提示稍后再试。

### QQ 音乐

支持三种方式登录 QQ 音乐：

- QQ 扫码
- 微信扫码
- 手机号 + 短信验证码（可能需要先在浏览器里完成一次人机验证，页面会给出验证链接）

登录成功后会拿到完整的登录凭证（`musickey`、`refresh_key`、`refresh_token`、`openid` 等），可以选择保存为主账号（`module.tx.user`）或加入 cookie 池（`module.cookiepool.tx`），并可同时开启该账号的自动刷新登录。保存后配置会自动热重载，刷新任务立即生效，不需要再手动抓包、复制 key。

说明：

- 登录得到的凭证只在服务端内存里保留 10 分钟，点击“保存到配置”后才会写入配置文件；状态接口不会返回凭证本身。
- 手机号登录会用到一份模拟的安卓设备信息，保存在 `config/tx_device.json`（含向官方申请的 QIMEI，24 小时刷新一次），请不要删除或公开。
- 暂不支持“手机 QQ 音乐客户端扫码”这种需要 MQTT 的登录方式。
- 登录协议参考了 [YAQMC/qm-api-rs](https://github.com/YAQMC/qm-api-rs)（GPL-3.0）的文档与行为，代码是独立实现的，没有复制其源码；QIMEI/设备信息部分参考了同源项目 [MeoProject/lx-music-api-server](https://github.com/MeoProject/lx-music-api-server)（MIT）。

## 模块状态

后台“模块状态”除了检查平台域名是否可达、必填配置是否齐全之外，还会反映登录保活任务是否在连续失败，以及 QQ 音乐账号的登录凭证是否已经失效（检查结果缓存 30 分钟，点击“立即检查”会重新检查）。公开首页上只显示笼统状态，具体的任务名、账号信息只有登录后台的管理员能看到。

## 数据库说明

当前分支使用 SQLite：

- `app.db`：用户、管理员、解析日志、模块健康状态
- `config/data.db`：封禁列表、请求时间等运行数据
- `cache.db`：HTTP 缓存

解析统计里的记录默认保留 30 天，超期的每天自动清理，可通过 `common.parse_log_retention_days` 调整（0 表示不清理）。

仓库已不再跟踪 `users.db`、`*.db`、`config/`、`logs/` 和 `__pycache__`（见 `.gitignore`），这些都是运行时生成的文件。

后续计划：

- 数据库支持 MySQL

## 安全建议

- 部署后请立即修改管理员密码（至少 8 位）。管理员密码使用加盐的 scrypt 保存，旧版本的 sha256 密码会在下次登录成功时自动升级；改密码后该管理员的其他登录会话会失效。
- 后台登录同一 IP 15 分钟内失败 5 次会被暂时限制；后台会话 4 小时无操作或登录满 24 小时后需要重新登录。
- 后台的所有修改操作都通过 JSON 接口完成（POST/PUT/PATCH/DELETE，必须是 `application/json` 请求体），会校验请求的 `Origin`/`Referer` 与访问的 Host 一致，后台 Cookie 为 `HttpOnly` + `SameSite=Strict`；页面带有严格的 CSP（不允许内联脚本和样式）。如果你的反向代理改写了 Host，导致后台操作提示“请求来源校验失败”，请让代理透传原始 Host（或设置 `X-Forwarded-Host`），或把配置 `security.admin_origin_check` 设为 `false`。
- 通过 HTTPS 反向代理访问时，请把 `common.ssl_info.is_https` 设为 `true`，后台 Cookie 才会带上 `Secure` 标记。
- `security.rate_limit` 的限速只作用于解析接口（含首页的在线解析），后台页面、静态文件和后台接口不受限速影响，否则打开一个页面就会因为同时加载多个文件而被限速。
- API Key 不会再写入日志。
- 不要公开真实 API Key、平台 cookie、token、session。
- 生产环境建议放在 HTTPS 反向代理后。
- 如果仓库曾提交过真实 `users.db` 或配置文件，请轮换相关 Key。

## 开发说明

检查语法：

```bash
python -m compileall -q common modules main.py webui
```

运行单元测试（测试会在临时目录里运行，不会改动仓库里的配置和数据库）：

```bash
python -m unittest discover -s tests
```

查看当前 Git 状态：

```bash
git status -sb
```
