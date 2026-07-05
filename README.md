# lx-api-server

基于 `lx-music-api-server` 改造的多音源解析服务，当前分支将 API 鉴权调整为 SQLite 用户 + Key 模式，并加入 Web 管理后台、解析统计、模块健康检查和登录保活任务。

## 功能概览

- 支持酷狗、QQ 音乐、网易云、咪咕、酷我等音源解析。
- 使用 `X-Request-User` 和 `X-Request-Key` 做 API 请求鉴权。
- 提供 Web 管理后台，可管理配置、API 用户、解析统计、模块健康状态和管理员密码。
- 支持普通单账号模式和 cookie 池模式。
- 支持 QQ 音乐、酷狗、网易云、咪咕的自动刷新登录/保活任务。
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

启动后可通过日志确认任务是否注册：

```text
scheduler loaded 1 task(s): qqmusic_refresh_login
```

cookie 池模式示例：

```text
scheduler loaded 1 task(s): qqmusic_refresh_login_pooled_0
```

如果日志中没有 QQ 音乐刷新任务，请优先检查：

- `common.cookiepool` 是否符合当前使用模式
- `module.tx.user.refresh_login.enable`
- `module.cookiepool.tx[*].refresh_login.enable`
- `module.tx.user.qqmusic_key` 或 `module.cookiepool.tx[*].qqmusic_key`

## 配置热重载

后台保存配置并选择热重载后，会重新加载配置并重建定时任务。刷新登录任务会按最新配置重新注册，cookie 池账号会在任务执行时读取当前配置，避免继续使用启动时的旧 token/key/session。

## 数据库说明

当前分支使用 SQLite：

- `app.db`：用户、管理员、解析日志、模块健康状态
- `config/data.db`：封禁列表、请求时间等运行数据
- `cache.db`：HTTP 缓存

后续计划：

- 数据库支持 MySQL
- 清理运行产物和本地数据库文件的仓库跟踪

## 安全建议

- 部署后请立即修改管理员密码。
- 不要公开真实 API Key、平台 cookie、token、session。
- 生产环境建议放在 HTTPS 反向代理后。
- 如果仓库曾提交过真实 `users.db` 或配置文件，请轮换相关 Key。

## 开发说明

检查语法：

```bash
python -m compileall -q common modules main.py webui
```

查看当前 Git 状态：

```bash
git status -sb
```
