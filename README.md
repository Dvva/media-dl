# media-dl

输入一个链接，自动识别平台并下载其中的图片 / 视频。为 Termux（Android）设计，也能在桌面端 Python 环境跑。

支持平台：**Twitter/X、小红书、抖音、TikTok、哔哩哔哩、Telegram**

- 一条推文里的**所有**图片、视频、GIF 一次性下完
- 单条抖音 / 小红书 / TikTok 视频或图文笔记自动判断
- 文件名模板可配置，支持平台级覆盖
- 封面可存成同名 `.jpg`，也可嵌进 mp4
- 默认 720P，可命令行覆盖
- 遇到私密 / 付费 / 作者关闭下载时明确跳过并记录原因，不无脑重试

---

## 一、安装（Termux）

```bash
pkg update
pkg install python ffmpeg          # ffmpeg 是硬依赖（分片视频合并用）
termux-setup-storage               # 允许写入 /sdcard

git clone <你的仓库地址> ~/media-dl
cd ~/media-dl
pip install -r requirements.txt
```

装完验证：

```bash
python dl.py --help
```

> `yt-dlp` 和 `gallery-dl` 必须能在 `PATH` 里找到，脚本靠它们下载 TikTok / B站 / TG / 推特。

## 二、用法

```bash
# 直接贴链接
python dl.py "https://x.com/user/status/1234567890"

# 贴整段分享文案也行，脚本自己抠链接
python dl.py "3.45 复制打开抖音，看看【某作者】的作品 https://v.douyin.com/xxxx/"

# 指定封面方式与画质
python dl.py --cover embed --quality 1080 "https://www.bilibili.com/video/BVxxxx"

# 只识别平台，不下载（调试用）
python dl.py --dry-run "https://www.xiaohongshu.com/explore/xxxx"
```

参数：

| 参数 | 说明 |
|---|---|
| `--out DIR` | 覆盖输出目录 |
| `--quality 720/1080` | 画质上限，默认取配置的 720 |
| `--cover sidecar/embed/both/none` | 封面处理方式 |
| `--config FILE` | 追加一个配置文件 |
| `--dry-run` | 只识别不下载 |
| `-v` | 调试输出 |

## 三、代理

手机用 **flclash** 时，默认混合端口是 7890，`config.toml` 里已经写好：

```toml
[general]
proxy = "http://127.0.0.1:7890"
```

留空则读环境变量 `ALL_PROXY` / `HTTPS_PROXY`。代理会同时传给 `yt-dlp`、`gallery-dl` 和内置的 requests 会话。

## 四、Cookie 怎么拿（重点）

推特、小红书、B站基本都需要登录态。统一格式是 **Netscape cookies.txt**，放 `~/cookies/<平台名>.txt`。

### 推荐做法：浏览器扩展导出

1. 桌面 Chrome / Edge 或手机 **Kiwi Browser**（支持 Chrome 扩展）安装扩展 **Get cookies.txt LOCALLY**（开源，只写本地文件，不上传）。
2. 登录对应网站。
3. 点扩展图标 → Export → 得到 `xxx_cookies.txt`。
4. 传到手机，改名放进 `~/cookies/`：

```bash
mkdir -p ~/cookies
cp ~/storage/shared/Download/twitter_cookies.txt ~/cookies/twitter.txt
chmod 600 ~/cookies/*.txt
```

### 各平台至少需要的字段

| 平台 | 关键 cookie | 说明 |
|---|---|---|
| Twitter/X | `auth_token`、`ct0` | 两条就够，不用整份 |
| 小红书 | `a1`、`web_session` | **没有 `a1` 会被直接 461** |
| B站 | `SESSDATA`（必需）、`bili_jct` | 720P 以上必须登录 |
| TikTok | `sessionid`、`tt_chain_token` | 单条视频很多时候不登也能下 |
| 抖音 | 一般不需要 | 单条解析走分享页，用不上 cookie |

> 导出后尽快用；cookie 会过期，失效时脚本会报 `SKIP_PRIVATE` 或 461，重新导一次即可。

## 五、文件名模板

在 `config.toml` 的 `[naming]` 段配置：

```toml
[naming]
default = "{platform}_{id}_{index}"     # 全局默认
tiktok  = "tiktok_{author}_{id}"        # 平台级覆盖，优先级更高
omit_index_when_single = true           # 只有一个文件时自动省掉 {index}
```

可用变量：

| 变量 | 含义 | 示例 |
|---|---|---|
| `{platform}` | 平台名 | xhs |
| `{author}` | 作者昵称 | 某某某 |
| `{author_id}` | 作者 ID | 5f2e... |
| `{id}` | 内容 ID | 66abcdef... |
| `{title}` | 标题或文案 | 周末去哪玩 |
| `{date}` | 日期 `YYYYMMDD` | 20261105 |
| `{datetime}` | 日期时间 | 20261105_1842 |
| `{index}` | 多文件序号（`01`、`02`） | 01 |
| `{type}` | `video` / `image` | video |

规则说明：

- 只有一个文件时 `{index}` 整段被剔除，不会出现 `xxx_01` 的孤零零后缀。
- 模板里可以用 `/` 建子目录，比如 `{platform}/{author}/{date}_{id}`。
- 文件名非法字符自动替换为 `_`（FAT32 存储不能含 `: * ? " < > |`）。

## 六、配置项

```toml
[general]
output_dir = "~/storage/shared/Download/media"
proxy      = "http://127.0.0.1:7890"

[quality]
max_height = 720              # 720P

[cover]
enabled    = true
mode       = "sidecar"        # sidecar | embed | both | none

[platforms]
enabled    = ["twitter", "xhs", "douyin", "tiktok", "bilibili", "telegram"]

[cookies]
dir        = "~/cookies"
```

需要本地私有配置时，新建 `config.local.toml` 覆盖同名项（已在 `.gitignore` 里）。

## 七、跳过原因说明

脚本不会无脑重试，失败会落到下面这些状态，写进日志和退出码：

| 状态 | 含义 | 能不能解决 |
|---|---|---|
| `SKIP_PRIVATE` | 私密账号 / 好友可见 / 未登录 | 换有权限的 cookie |
| `SKIP_DELETED` | 已删除 / 已下架 | 无解 |
| `SKIP_PAYWALLED` | 付费 / 会员限定 | 需要有效订阅 |
| `SKIP_AUTHOR_DISABLED` | 作者关闭了下载 | 尊重作者意愿，不绕过 |
| `SKIP_NO_MEDIA` | 解析成功但没有媒体 | 内容本身如此 |
| `FAIL_NETWORK` | 网络 / 风控（如小红书 461） | 换代理、更新 cookie、降频 |
| `FAIL_PARSE` | 页面结构变了 | 需要更新解析代码 |
| `FAIL_TOOL` | yt-dlp / gallery-dl 失败 | 看日志里的 stderr |

## 八、已知限制

- **Telegram 只支持公开频道的 `t.me/频道/消息号`**，私有群、需要加入的频道不支持（要加 Telethon 后端）。
- **小红书风控最严**，请求频率过高会 461，建议保持 `delay_sec = 3` 以上。
- **抖音单条走分享页 SSR**，不需要签名；但主页批量下载不在本工具范围内。
- 视频不转码，`--quality` 只影响 yt-dlp 选流；直链下载的平台（抖音、小红书）无法改画质。

## 九、目录结构

```
media-dl/
├── dl.py                  # 入口
├── config.toml            # 默认配置
├── core/
│   ├── config.py          # 配置加载与合并
│   ├── detect.py          # URL → 平台
│   ├── naming.py          # 模板渲染
│   ├── http.py            # 会话 / cookie / 重试
│   ├── downloader.py      # 直链下载
│   ├── finalize.py        # 外部工具产物归档
│   ├── cover.py           # 封面 sidecar / embed
│   └── result.py          # 状态枚举
└── platforms/
    ├── base.py            # 数据结构
    ├── gallerydl_backend.py  # twitter
    ├── ytdlp_backend.py      # tiktok / bilibili / telegram
    ├── douyin.py             # 抖音
    └── xhs.py                # 小红书
```
