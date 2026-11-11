# media-dl

输入一个链接，自动识别平台并下载图片 / 视频。为 Termux（Android）设计，也能在 Windows 桌面端跑。

支持平台：**Twitter/X、小红书、抖音、TikTok、哔哩哔哩、Telegram、YouTube**

- 一条推文里的**所有**图片、视频、GIF 一次性下完
- 文件名统一成 `平台_作者_id` 形状，默认从左到右可逆：能从文件名拆回字段、拼回作品网址
- 下载 / 改名 / 替换后，**文件时间改成作品发布时间**
- 下载只显示本项目进度条，不打印 yt-dlp / gallery-dl 的调用命令和刷屏日志
- 文件名里的非法字符、emoji、零宽字符**默认删除**（不替换成下划线）
- 支持从文件名反推网址：`redl` 重下、`rename` 改名、`replace` 换清晰度
- 支持多参数、分享文案、多个链接直接拼接；非链接参数自动忽略
- 默认 720P，可命令行覆盖；遇到私密 / 付费 / 作者关闭下载时明确跳过并记录原因

---

## 一、安装

### Termux

```bash
pkg update
pkg install python ffmpeg          # ffmpeg 是硬依赖（分片视频合并用）
termux-setup-storage               # 允许写入 /sdcard

git clone <你的仓库地址> ~/media-dl
cd ~/media-dl
pip install -r requirements.txt
```

### Windows

```powershell
D:\__Scoop\apps\python311\current\python.exe -m pip install -r requirements.txt
```

`yt-dlp` 和 `gallery-dl` 必须能在 `PATH` 里找到。Windows 上如需“删除进回收站”，额外装 `send2trash`；
没装时会退回到下载目录旁的 `.trash\日期\`，不会直接永久删除。

装完验证：

```bash
python dl.py --help
python dl.py --check-config
```

---

## 二、命令

| 命令 | 作用 |
|---|---|
| `dl.py URL...` | 下载。第一个参数不是子命令时就是它，旧用法完全兼容 |
| `dl.py redl 清单.txt` | 从文件里的 URL / 视频 id 重新下载 |
| `dl.py rename 目录` | 按文件名反推网址、取属性后重新命名（默认预览） |
| `dl.py replace --quality 1080 文件` | 按文件名重建网址，用新清晰度重下并替换（默认预览） |
| `dl.py probe URL或文件` | 只解析属性、不下载，打印将生成的文件名 |
| `dl.py doctor 目录` | 检查哪些文件名无法重建网址 |

示例：

```bash
# 直接贴链接
python dl.py "https://x.com/user/status/1234567890"

# 贴整段分享文案；多个参数；多个链接直接拼接（只取有效 URL，其他参数忽略）
python dl.py "看看这个https://x.com/a/status/1复制https://x.com/b/status/2" 乱七八糟的参数

# 从清单重下（每行一个 URL，或 "平台 id"）
python dl.py redl list.txt
python dl.py redl --platform twitter 1234567890 9876543210

# 按文件名重建网址并改名（先预览，确认后加 --apply）
python dl.py rename ./downloads
python dl.py rename --apply ./downloads

# 换清晰度替换；文件名第 1 段是作者、第 2 段是作品 id
python dl.py replace --quality 1080 --pattern "{1}_{2}" ./twitter_foo_123.mp4
python dl.py replace --apply --quality 1080 ./tiktok_bodikaidenandi_7667479697651010823.mp4

# 只识别，不下载
python dl.py --dry-run "https://www.xiaohongshu.com/explore/xxxx"

# 检查旧文件名能否反推网址
python dl.py doctor "G:\____\.文件下载"
```

参数：

| 参数 | 说明 |
|---|---|
| `--out DIR` | 覆盖输出目录 |
| `--quality 720/1080` | 画质上限 |
| `--cover sidecar/embed/both/none` | 封面处理方式 |
| `--config FILE` | 追加一个配置文件 |
| `--dry-run` | 只识别 / 预览，不下载 |
| `--no-proxy` | 本次忽略代理，直连 |
| `--overwrite` | 目标存在时先备份再覆盖（默认跳过） |
| `--from-file FILE` | 从文件读取 URL / ID，可重复 |
| `--pattern "..."` | 反向解析模板，如 `{platform}_{1}_{2}` |
| `--platform NAME` | 手动指定平台（裸 id / 无平台前缀的文件名） |
| `--apply` | `rename` / `replace` 真正执行 |
| `--tag 1080p` | `replace` 后给文件名加后缀 |
| `--progress bar/none` | 进度条开关（`--no-progress` 同义） |
| `--print-config` | 打印生效配置及来源 |
| `--check-config` | 只校验配置，退出码 0/1/2 |
| `-v` | 调试输出 |

---

## 三、命名规则（重点）

### 1. 默认模板

```toml
[naming]
default  = "{platform}_{author}_{id}_{index}"
twitter  = "twitter_{author}_{id}"
tiktok   = "tiktok_{author}_{id}"
xhs      = "xhs_{author}_{id}"
douyin   = "douyin_{author}_{id}"
bilibili = "bilibili_{author}_{id}"
youtube  = "youtube_{author}_{id}"
telegram = "telegram_{author}_{id}"
```

- `{author}` 是**能重建网址的稳定标识**：推特 / TikTok 用 handle，小红书 / 抖音用昵称，B站 / YouTube / Telegram 用频道名。
- 展示用昵称用 `{nickname}`。
- 单文件时 `{index}` 整段去掉；多文件追加 `_01`、`_02`。
- 文件名非法字符、emoji、零宽字符会被删除，不会变成下划线；清空后退回 `untitled`。

### 2. 反向解析（文件名 → 字段 → 网址）

```toml
[urls]
twitter  = "https://x.com/i/status/{id}"
xhs      = "https://www.xiaohongshu.com/explore/{id}"
douyin   = "https://www.douyin.com/video/{id}"
tiktok   = "https://www.tiktok.com/@{author}/video/{id}"
bilibili = "https://www.bilibili.com/video/{id}"
youtube  = "https://www.youtube.com/watch?v={id}"
telegram = "https://t.me/{author}/{id}"
```

也能在命令行用位置写法：

```bash
--pattern "{1}_{2}"        # {1}=作者，{2}=作品 id
--pattern "{platform}_{author}_{id}"
```

旧文件可在 `[patterns]` 里加额外模板：

```toml
[patterns]
legacy = ["{platform}-{author}-{id}", "旧前缀_{id}"]
```

### 3. 哪些文件名无法重建

- 推特旧名 `<tweet_id>-<hash>.jpg`：没有平台名时无法确定平台；带 `twitter_` 前缀可以，但作者要联网补。
- TikTok 只有昵称、没有 `@handle`：拼不出可访问网址。
- Telegram 文件名缺频道名或消息号：拼不出 `t.me/频道/消息号`。
- 文件名里没有作品 id：只能人工处理。

**首次运行会提醒一次**；也可以随时运行 `dl.py doctor <目录>` 查看具体清单。
`rename` / `redl` 遇到这类文件会跳过并打印原因，不会硬改名。

---

## 四、新功能说明

### 1. 文件时间 = 作品发布时间

下载、`rename`、`replace` 成功后都会 `os.utime` 写回发布时间；封面 `.jpg` 同样处理。
关掉：`[behavior] set_mtime = false`。

### 2. redl：从文件 / 目录 / 文件名重新下载

支持：

- 文本清单（每行 URL、`平台 id`、`平台:ID`，`#` 开头为注释）
- 目录（扫描媒体文件，按文件名反推网址）
- 单个媒体文件（按文件名反推）
- 裸 id（必须配 `--platform`）

### 3. rename：按文件名重建网址后改名

1. 文件名 → 字段；
2. 拼网址；
3. 联网取作者 / id / 发布时间（`--apply` 时才联网）；
4. 用当前 `[naming]` 模板重新渲染；
5. 同名封面 `.jpg` 一起改；
6. 目标已存在时按 `behavior.overwrite` 备份或跳过。

默认只预览，必须加 `--apply` 才动文件。

### 4. replace：换清晰度重下并替换

- 文件名 → 网址；
- 按 `--quality` 重新下载到临时目录；
- 旧文件**移动到备份目录**（`~/.local/state/media-dl/backup/日期/`），不删除；
- 新文件替换原路径，写回发布时间；
- 失败时保留旧文件；
- 抖音 / 小红书直链清晰度固定，会明确提示不支持换清晰度。

### 5. 多参数 / 拼接链接

```bash
python dl.py "https://a.com/xhttps://b.com/y" 无意义参数
```

会拆成两个 URL，忽略无意义参数；重复链接自动去重。

---

## 五、代理与 Cookie

手机用 **flclash** 时默认混合端口 7890，`config.toml` 已写好。留空则读 `ALL_PROXY` / `HTTPS_PROXY`。
代理连不上会自动降级直连，并打一行警告；强制直连用 `--no-proxy`。

Cookie 统一用 **Netscape cookies.txt**，放 `~/cookies/<平台名>.txt`：

| 平台 | 关键 cookie |
|---|---|
| Twitter/X | `auth_token`、`ct0` |
| 小红书 | `a1`、`web_session` |
| B站 | `SESSDATA`、`bili_jct` |
| TikTok | `sessionid`、`tt_chain_token` |
| 抖音 | 一般不需要 |

Termux 上：

```bash
mkdir -p ~/cookies
cp ~/storage/shared/Download/twitter_cookies.txt ~/cookies/twitter.txt
chmod 600 ~/cookies/*.txt
```

---

## 六、配置

配置模板见 `config.example.toml`。实际使用的 `config.toml` 已被 `.gitignore` 忽略，
不会进版本库；第一次使用可复制一份：

```bash
cp config.example.toml config.toml
```

读取优先级：**命令行 > 环境变量（代理）> config.local.toml > config.toml > 内置默认**。
`--print-config` 会标出每个值的来源；`--check-config` 只校验不执行。

---

## 七、Telegram 说明

- 支持公开频道的 `t.me/频道/消息号`，会下载视频、文件、图片（取决于 yt-dlp 对该帖的解析）。
- **暂时没有 tg_id**：文件名里的 `{id}` 可能为空，模板会退回 `unknown`；这类文件无法从文件名重建网址，`rename` / `redl` 会提示跳过。
- 私有群、需要加入的频道不支持。

---

## 八、跳过原因

| 状态 | 含义 |
|---|---|
| `SKIP_PRIVATE` | 私密账号 / 好友可见 / 未登录 |
| `SKIP_DELETED` | 已删除 / 已下架 |
| `SKIP_PAYWALLED` | 付费 / 会员限定 |
| `SKIP_AUTHOR_DISABLED` | 作者关闭了下载 |
| `SKIP_NO_MEDIA` | 解析成功但没有媒体 |
| `FAIL_NETWORK` | 网络 / 风控 |
| `FAIL_PARSE` | 页面结构变了 |
| `FAIL_TOOL` | yt-dlp / gallery-dl 失败 |

---

## 九、测试

离线单测（不需要网络）：

```bash
python -m unittest discover -s tests -v
```

真实链接清单在 `tests/data/links.txt`。探测（需要代理 / cookie）：

```bash
python tests/smoke_links.py --probe
python tests/smoke_links.py --download --limit 2
```

---

## 十、目录结构

```
media-dl/
├── dl.py                  # 入口 / 子命令
├── config.toml            # 本地配置（忽略）
├── config.example.toml    # 配置模板
├── core/
│   ├── config.py          # 配置加载、来源、校验
│   ├── urls.py            # 链接抽取 / 拼接拆分
│   ├── patterns.py        # 文件名模板正反向、网址重建
│   ├── naming.py          # 字符清理、模板渲染
│   ├── metadata.py        # 只取元数据（probe）
│   ├── batch.py           # redl / rename / replace / doctor
│   ├── fsops.py           # mtime / 备份 / 回收站
│   ├── downloader.py      # 直链下载
│   ├── finalize.py        # 外部工具产物归档
│   ├── toolrun.py         # 静默调用外部工具、解析进度
│   ├── http.py            # 会话 / cookie / 重试
│   ├── cover.py           # 封面 sidecar / embed
│   ├── merge.py           # 图片横向拼接
│   ├── progress.py        # 进度条
│   └── result.py          # 状态枚举
├── platforms/
│   ├── base.py
│   ├── gallerydl_backend.py  # twitter（优先直链）
│   ├── ytdlp_backend.py      # tiktok / bilibili / telegram / youtube
│   ├── douyin.py
│   └── xhs.py
└── tests/
    ├── data/links.txt
    ├── smoke_links.py
    └── test_*.py
```
