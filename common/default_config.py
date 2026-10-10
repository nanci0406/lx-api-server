default = """\
common:
  hosts: # 服务器监听地址
    - 0.0.0.0
  # - '::' # 取消这一行的注释，启用 ipv6 监听
  ports: # 服务器启动时所使用的端口
    - 9763
  ssl_info: # 服务器https配置
    # 这个服务器是否是https服务器，如果你使用了反向代理来转发这个服务器，如果它使用了https，也请将它设置为true
    is_https: false
    # python原生https监听
    enable: false
    ssl_ports:
      - 443
    path: # ssl证书的文件地址
      cert: /path/to/your/cer
      privkey: /path/to/your/private/key
  reverse_proxy: # 针对类似于nginx一类的反代的配置
    allow_public_ip: false # 允许来自公网的转发
    allow_proxy: true # 是否允许反代
    real_ip_header: X-Real-IP # 反代来源ip的来源头，不懂请保持默认
  debug_mode: false # 是否开启调试模式
  log_length_limit: 500 # 单条日志长度限制
  parse_log_retention_days: 30 # 后台"解析统计"里解析记录的保留天数，超期记录每天自动清理，0 表示不清理
  fakeip: 1.0.1.114 # 服务器在海外时的IP伪装值
  proxy: # 代理配置，HTTP与HTTPS协议需分开配置
    enable: false
    http_value: http://127.0.0.1:7890
    https_value: http://127.0.0.1:7890
  log_file: true # 是否存储日志文件
  cookiepool: false # 是否开启cookie池，这将允许用户配置多个cookie并在请求时随机使用一个，启用后请在module.cookiepool中配置cookie，在user处配置的cookie会被忽略，cookiepool中格式统一为列表嵌套user处的cookie的字典
  allow_download_script: true # 是否允许直接从服务端下载脚本，开启后可以直接访问 /script?key=你的请求key 下载脚本
  download_config: # 源脚本的相关配置
    name: 修改为你的源脚本名称
    intro: 修改为你的源脚本描述
    author: 修改为你的源脚本作者
    version: 修改为你的源版本
    filename: lx-music-source.js # 客户端保存脚本时的文件名（可能因浏览器不同出现不一样的情况）
    dev: true # 是否启用开发模式
    update: true # 是否开启脚本更新提醒
    # 可用参数
    # {updateUrl}为更新地址(带请求key)
    # {url}为请求时的url(不带请求的param)
    # {key}为请求时携带的key
    updateMsg: "源脚本有更新啦，更新地址:\\n{updateUrl}"
    quality:
      kg: [128k]
      tx: [128k]
      wy: [128k]
  local_music: # 服务器侧本地音乐相关配置，如果需要使用此功能请确保你的带宽足够
    audio_path: ./audio
    temp_path: ./temp

security:
  rate_limit:
    global: 0
    ip: 0
  key:
    enable: true
    ban: true
  admin_origin_check: true # 校验后台 POST 请求的 Origin/Referer 必须与访问的 Host 一致(防 CSRF)，反向代理改写了 Host 导致后台无法操作时可关闭
  whitelist_host:
    - localhost
    - 0.0.0.0
    - 127.0.0.1
  check_lxm: false
  lxm_ban: true
  allowed_host:
    enable: false
    blacklist:
      enable: false
      length: 0
    list:
      - localhost
      - 0.0.0.0
      - 127.0.0.1
  banlist:
    enable: true
    expire:
      enable: true
      length: 604800

module:
  kg: # 酷狗音乐相关配置
    enable: true # 是否开启本平台服务
    client: # 客户端请求配置，不懂请保持默认，修改请统一为字符串格式
      appid: "1005" # 酷狗音乐的appid，官方安卓为1005，官方PC为1001
      signatureKey: OIlwieks28dk2k092lksi2UIkp # 客户端signature采用的key值，需要与appid对应
      clientver: "12029" # 客户端versioncode，pidversionsecret可能随此值而变化
      pidversionsecret: 57ae12eb6890223e355ccfcb74edf70d # 获取URL时所用的key值计算验证值
      pid: "2" # url接口的pid
    tracker: # trackerapi请求配置，不懂请保持默认，修改请统一为字符串格式
      host: https://gateway.kugou.com
      path: /v5/url
      version: v5
      x-router: # 当host为gateway.kugou.com时需要追加此头，为tracker类地址时则不需要
        enable: true
        value: tracker.kugou.com
      extra_params: {} # 自定义添加的param，优先级大于默认，填写类型为普通的JSON数据，会自动转换为请求param
    user: # 此处内容请统一抓包获取（/v5/url），需要vip账号来获取会员歌曲，如果没有请留为空值，mid必填，可以瞎填一段数字
      token: ""
      userid: "0"
      mid: "114514"
      lite_sign_in: # 是否启用概念版自动签到，仅在appid=3116时运行
        enable: false
        interval: 86400
        mixsongmid: # mix_songmid的获取方式, 默认auto, 可以改成一个数字手动
          value: auto
      refresh_login: # 酷狗token保活相关配置，30天不刷新token会失效，enable是否启动，interval刷新间隔。默认appid=1005时有效，3116需要更换signatureKey
        enable: false
        interval: 86000
        login_url: http://login.user.kugou.com/v4/login_by_token

  tx: # QQ音乐相关配置
    enable: true # 是否开启本平台服务
    vkeyserver: # 请求官方api时使用的guid，uin等信息，不需要与cookie中信息一致
      guid: "114514"
      uin: "10086"
    user: # 用户数据，可以通过浏览器获取，需要vip账号来获取会员歌曲，如果没有请留为空值，qqmusic_key可以从Cookie中/客户端的请求体中（comm.authst）获取
      qqmusic_key: ""
      uin: "" # key对应的QQ号
      # 以下是刷新登录所需的凭证，来自登录时返回的数据(music.login.LoginServer)，没有可留空
      # 刷新成功后会自动更新这些字段。手动更换 qqmusic_key 时请一并更新它们，否则会用旧凭证刷新
      refresh_key: ""
      refresh_token: ""
      openid: ""
      access_token: ""
      unionid: ""
      login_type: "" # 登录方式：1 微信，2 QQ，其他为手机验证码等。通过后台"QQ 登录"页登录时自动填写，手动配置时可留空
      refresh_login: # 刷新登录相关配置，enable是否启动，interval刷新间隔
        enable: false
        interval: 86000
    cdnaddr: http://ws.stream.qqmusic.qq.com/
    vkey_api: # 第三方Vkey获取API
      use_vkey_api: false
      vkey_api_url: "xxx"

  wy: # 网易云音乐相关配置
    enable: true # 是否开启本平台服务
    user:
      cookie: "" # 账号cookie数据，可以通过浏览器获取，需要vip账号来获取会员歌曲，如果没有请留为空值
      refresh_login:
        enable: false
        interval: 86400

  gcsp: # 歌词适配后端配置
    # 请注意只允许私用，不要给原作者带来麻烦，谢谢
    enable: false # 是否启用歌词适配后端
    path: /client/cgi-bin/api.fcg # 后端接口地址
    enable_verify: false # 是否启用后端验证
    package_md5: "" # apk包的md5值，用于验证
    salt_1: "NDRjZGIzNzliNzEe" # 后端验证参数1
    salt_2: "6562653262383463363633646364306534333668" # 后端验证参数2

  cookiepool:
    kg:
      - userid: "0"
        token: ""
        mid: "114514"
        lite_sign_in: # 是否启用概念版自动签到，仅在appid=3116时运行
          enable: false
          interval: 86400
          mixsongmid: # mix_songmid的获取方式, 默认auto, 可以改成一个数字手动
            value: auto
        refresh_login: # cookie池中对于此账号刷新登录的配置，账号间互不干扰
          enable: false
          login_url: http://login.user.kugou.com/v4/login_by_token

    tx:
      - qqmusic_key: ""
        uin: ""
        refresh_key: "" # 刷新登录所需的凭证，说明见 module.tx.user，没有可留空
        refresh_token: ""
        openid: ""
        access_token: ""
        unionid: ""
        login_type: ""
        refresh_login: # cookie池中对于此账号刷新登录的配置，账号间互不干扰
          enable: false
          interval: 86000

    wy:
      - cookie: ""
        refresh_login: # cookie池中对于此账号刷新登录的配置，账号间互不干扰
          enable: false
          interval: 86400
"""
