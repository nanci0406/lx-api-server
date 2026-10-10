# lx-api-server

基于 `lx-music-api-server` 改造的多音源解析服务，当前分支将 API 鉴权调整为 SQLite 用户 + Key 模式，并加入 Web 管理后台、解析统计、模块健康检查和登录保活任务。

## 功能概览

- 支持酷狗、QQ 音乐、网易云音源解析（咪咕、酷我已移除）。
- 使用 `X-Request-User` 和 `X-Request-Key` 做 API 请求鉴权。
- 提供 Web 管理后台，可管理配置、API 用户、解析统计、模块健康状态和管理员密码。
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

- 配置管理
- API 用户管理
- 解析统计
- 模块健康状态
- 管理员密码管理

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

后台保存配置并选择热重载后，会重新加载配置并重建定时任务。刷新登录任务会按最新配置重新注册，cookie 池账号会在任务执行时读取当前配置，避免继续使用启动时的旧 token/key/session。

## 模块状态

后台“模块状态”除了检查平台域名是否可达、必填配置是否齐全之外，还会反映登录保活任务是否在连续失败，以及 QQ 音乐账号的登录凭证是否已经失效（检查结果缓存 30 分钟，点击“立即刷新”会重新检查）。公开首页上只显示笼统状态，具体的任务名、账号信息只有登录后台的管理员能看到。

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
- 后台的退出、热重载、刷新等操作都是 POST 请求，并且会校验请求的 `Origin`/`Referer` 与访问的 Host 一致。如果你的反向代理改写了 Host，导致后台操作提示“请求来源校验失败”，请让代理透传原始 Host（或设置 `X-Forwarded-Host`），或把配置 `security.admin_origin_check` 设为 `false`。
- 通过 HTTPS 反向代理访问时，请把 `common.ssl_info.is_https` 设为 `true`，后台 Cookie 才会带上 `Secure` 标记。
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
