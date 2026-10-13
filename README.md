# sd_spider_utils

常用爬虫工具：文本清洗、HTML 文本提取、JSON/Excel 转换、DrissionPage
辅助函数，以及可按请求切换下载后端的 Scrapy 中间件。

## 安装

```bash
pip install sd_spider_utils
```

按需安装额外功能：

```bash
pip install "sd_spider_utils[excel]"        # pandas、openpyxl
pip install "sd_spider_utils[xpath]"        # lxml
pip install "sd_spider_utils[scrapy]"       # Scrapy 文本解析
pip install "sd_spider_utils[requests-go]"  # Scrapy + requests-go
pip install "sd_spider_utils[curl-cffi]"    # Scrapy + curl-cffi
pip install "sd_spider_utils[drissionpage]" # Scrapy + DrissionPage
pip install "sd_spider_utils[scrapling]"    # Scrapy + Scrapling
pip install "sd_spider_utils[all]"          # 安装全部可选功能
```

Scrapling 首次使用还需执行 `scrapling install` 下载浏览器。

## 开发环境（uv）

先按 [uv 官方文档](https://docs.astral.sh/uv/getting-started/installation/) 安装 uv，
然后在项目根目录执行：

```bash
uv sync --locked
```

uv 会按 `.python-version` 使用 Python 3.12（缺少时自动下载），创建 `.venv`，
并以可编辑模式安装项目及开发依赖。依赖统一在 `pyproject.toml` 中声明，
`uv.lock` 纳入版本控制，不再维护 `requirements.txt`。

```bash
uv sync --locked --all-extras  # 安装全部可选功能
uv run --extra scrapling scrapling install  # 使用 Scrapling 时下载浏览器
uv add 包名                   # 添加运行依赖并更新锁文件
uv add --dev 包名             # 添加开发依赖并更新锁文件
uv lock --upgrade            # 主动升级锁定的依赖
```

通过 `uv run --extra 名称 ...` 或 `uv run --all-extras ...` 运行需要可选功能的命令。
提交依赖变更时同时提交 `pyproject.toml` 和 `uv.lock`。

## Steam 评测导出命令

安装包含此功能的版本后可直接运行 `sd-steam-reviews`，无需 Steam 账号、Cookie、
API Key、数据库或额外依赖。源码开发先执行 `uv sync --locked`，
再用 `uv run sd-steam-reviews ...` 运行；pip 安装用户直接使用以下命令。

```bash
# 任意 Steam 游戏：AppID 可从商店地址 /app/ 后的数字获取
sd-steam-reviews --appid 246420 --language schinese
# 王国保卫战 1～5 的快捷选择；all 表示全部语言
sd-steam-reviews --kingdom-rush 1 --language all
# 指定文件，再次运行相同命令自动增量采集
sd-steam-reviews --appid 246420 --output "./data/reviews.jl"
# 查看所有选项，也可通过模块方式运行
sd-steam-reviews --help
python -m sd_spider_utils.steam_reviews --appid 246420
```

每次采集一个游戏，默认语言为 `schinese`（简体中文），也支持 `english`、`tchinese`、
`all` 等 Steam 语言代码。先请求首屏，显示评论总数、请求量估算和输出位置；
**直接按回车才开始写入，输入其他内容或结束输入则取消**。默认文件位于当前工作目录的
`steam_reviews/<appid>_<language>.jl`，每行是完整评测 JSON，附加 `_collection`
记录游戏、查询语言和 UTC 抓取时间。中文及正文换行会正确保留。

- `--mode auto`（默认）：首次完整初始化，完成后再次运行只采集新增时间段，按评测 ID 去重。
- `--mode init`：完整初始化，拒绝覆盖非空文件。
- `--mode incremental`：要求已有数据文件；缺少成功状态时先完整扫描、去重补齐。
- `--mode full`：重新扫描所有历史并去重追加，可补充延迟公开或后来改变语言的旧评测。
- `--page-size 100`：每页 1～100 条；`--interval 1`：请求间隔至少 1 秒。

请将 `.jl` 和同名 `.jl.state.json` 一起保留，并避免同时运行两个任务写同一文件。
失败不会推进成功时间边界，已写入的完整记录保留；重跑同一命令即可去重补采。
增量不覆盖旧评测的修改，也不删除已保存内容。文件损坏或游戏/语言不匹配时停止，避免混写。
退出码为 `0` 成功或取消、`1` 采集失败、`2` 参数错误、`130` 用户中断。

命令使用 Steam 官方公开的
[GetAppReviews 接口](https://partner.steamgames.com/doc/webapi/IUserReviewsService)，
包含全部好差评、购买来源和离题评测，但仅能导出接口公开返回的内容。
匿名响应可能缓存最多 10 分钟；限流或临时网络错误会有限重试，长时间限流则退出保留进度。
命令不读取项目的账号配置；默认输出目录已加入 Git 忽略规则，采集结果无需放入包内。

## Codex 用量命令

开发目录先执行 `uv sync --locked`，然后复制根目录的
`codex.env.example` 为 `codex.env`，填入 ChatGPT 登录生成的 `auth.json`
中 `tokens.access_token` 和 `tokens.account_id`：

```dotenv
CODEX_ACCESS_TOKEN=your-access-token
CODEX_ACCOUNT_ID=your-account-id

# 可继续添加账号；同一账号使用相同名称
CODEX_WORK_ACCESS_TOKEN=your-work-access-token
CODEX_WORK_ACCOUNT_ID=your-work-account-id
```

账号名也可以放在末尾，例如 `CODEX_ACCESS_TOKEN_personal` 配
`CODEX_ACCOUNT_ID_personal`。名称区分大小写；两种写法不要重复定义同一账号字段。
示例占位值必须替换为真实凭据，暂不用的账号请将两行都注释掉。

```bash
uv run sd-codex-usage --env codex.env
uv run sd-codex-usage --env "D:/private/codex.env" --json --timeout 20
# 也可通过模块运行：
uv run python -m sd_spider_utils.codex_usage --env codex.env
```

输出各账号的套餐、已用/剩余百分比、实际窗口时长、额度重置时间（本地时区，
JSON 带 UTC 偏移）、距重置时长及查询时间；包含服务端提供的额外额度组。
默认使用一张 Rich 彩色汇总表，合并展示所有账号的套餐、用量、重置时间和重置卡，
账号按行分组。剩余额度大于 25% 为绿色、10%～25% 为黄色、
10% 及以下为红色，同时保留百分比文字。
主状态优先回答能否使用：窗口有余量且接口允许时显示绿色“当前可用”；
耗尽时显示红色“暂不可用 · 5 小时额度用尽”“暂不可用 · 本周额度用尽”或两者都用尽。
每个窗口分别显示“不可用 / 有余量”和剩余百分比，避免把本周有余量误读为当前能用。
恢复时间按所有已耗尽窗口中最长的重置倒计时估算；任一时间缺失则显示未知，
已到重置时间但仍耗尽时提示等待刷新。具体恢复以服务端为准。
若接口允许标志与已耗尽额度不一致，会额外注明；服务端拒绝时显示“暂不可用 · 服务端限制”，
缺失额度或接口未明确允许时显示“状态待确认”。
JSON 保留服务端的 `allowed` / `limit_reached` 原始值，不用显示层判断覆盖。
168 小时显示为“每周窗口”；例如 `177210` 秒显示为“2 天 1 小时 13 分 30 秒”，
日期显示为 `2026-09-25 14:21:03`。
重定向输出时自动关闭颜色；`--json` 仍保留原始秒数、时间戳和 ISO 时间，不添加颜色控制码。
更新代码后执行 `uv sync --locked` 同步依赖。
同时显示可用重置卡张数、每张返回卡片的状态和过期时间（本地时区）。
张数以服务端 `available_count` 为准，明细可能只返回部分卡片，不能用列表长度代替。
未提供过期时间显示“未知”，不推断为永不过期；未提供张数也不当作 0。
JSON 中对应 `rate_limit_reset_credits`，包含 `available_count` 和 `credits`。
明细查询失败时保留用量及用量接口给出的张数，并输出 `reset_credits_error`。
缺失字段显示“未知”，不会当作零用量，也不会推算固定 Token 总配额。
每次运行重新查询；不修改 env、不刷新登录令牌。单账号失败不影响其他账号查询。
退出码：`0` 全部成功，`1` 至少一个账号查询、主动检测或检测结果保存失败，`2` 参数、env 配置或检测依赖错误。

支持 UTF-8（含 BOM）、空行、注释、`export KEY=VALUE` 和单行单/双引号；
不执行 shell 表达式，不展开 `${变量}`，不读取其他环境变量中的账号凭据。
未加引号的值在“空白 + #”处开始注释。不支持多行值及引号内的转义。

需要沿用 Base64 后倒序的混淆格式时：

```bash
uv run sd-codex-usage --encode  # 隐藏输入，输出 base64rev: 前缀的完整值
uv run sd-codex-usage --decode # 隐藏输入，解码带前缀的值
```

把生成的完整值填入任一账号字段即可。已有的无前缀倒序 Base64 值需手动
补上 `base64rev:`。这是可逆混淆，不是加密；真实 `.env` / `*.env` 已加入
Git 忽略规则，勿提交凭据；编码、解码命令会把结果打印到终端。

默认额度查询只发出 GET 请求，固定访问以下两个只读接口：

- `https://chatgpt.com/backend-api/wham/usage`：用量和重置卡张数。
- `https://chatgpt.com/backend-api/wham/rate-limit-reset-credits`：重置卡明细。

**不会使用或兑换重置卡，不调用 `/consume` 接口，也没有使用重置卡的命令参数。**
使用系统代理设置
（包括 `HTTPS_PROXY`），校验 TLS 且禁止重定向。只适用于 ChatGPT 登录账号，
不能用普通 OpenAI API Key 或中转站 Key 替代。`401` 时重新登录后更新 env；
`403` 时检查权限或网络；`429` 时稍后再试。

接口和字段参考上下文中的
[Codex 源码](https://github.com/openai/codex/tree/7498521d288b9b3b96ffba4eedf089d8d6e06a84/codex-rs/codex-backend-openapi-models/src/models)
及[官方额度字段说明](https://learn.chatgpt.com/docs/app-server#rate-limits)。
重置卡查询契约参考 [Codex 后端客户端](https://github.com/openai/codex/blob/main/codex-rs/backend-client/src/client/rate_limit_resets.rs)
和[响应类型](https://github.com/openai/codex/blob/main/codex-rs/backend-client/src/types.rs)。
这是客户端后端接口，可能变动；本项目使用模拟响应测试，不保证每个网络环境均可直接访问。

PyCharm 运行配置可选择模块 `sd_spider_utils.codex_usage`，参数填写
`--env D:/private/codex.env`，解释器选择项目的 `.venv` 环境。

### Codex 模型指纹检测（gpt-6-astra / ultra）

安装可选依赖。程序优先使用 PATH 中的 `codex`；macOS 找不到命令时，
会查找 `/Applications` 或 `~/Applications` 中 ChatGPT.app 内置的 CLI，
无需为了此功能单独安装或修改终端 PATH。其他安装方式需确保 `codex` 在 PATH 中：

```bash
uv sync --locked --extra model-check
uv run --locked --extra model-check sd-codex-usage --env codex.env --detect
# 只检测 WORK 账号；无名称账号使用 --account '(默认)'
uv run --locked --extra model-check sd-codex-usage --env codex.env --detect --account WORK
```

固定使用 Codex 订阅模式、`gpt-6-astra`、`ultra`，没有切换型号或推理强度的参数。
通过本机 Codex app-server 的外部 ChatGPT 登录模式传入所选 env 账号的凭据，
在独立临时环境中生成三份数字挑战回答，再使用随包 ModelTrace 指纹库离线评分。
`ultra` 交给 Codex 运行时处理，不作为普通 API 的推理强度直接发送；
数字挑战禁止工具生成随机数，不测试自动委派能力。旧版 Codex 不支持相应协议或模式时会报错。
不读取当前 Codex 聊天，不更改常用登录；登录令牌仅通过子进程标准输入传递。
桌面应用内的 PATH 可能包含内置 CLI，而外部终端没有；应用内检查成功不能证明外部终端能找到命令。
额度查询的 HTTP 401 与 CLI 查找失败是两个独立问题：env 保存的是令牌副本，不会跟随桌面应用
自动刷新。401 时需重新取得对应账号的 `access_token` / `account_id` 并更新 env；
仅重新登录桌面应用而不更新 env，不会改变本命令使用的凭据。

**`--detect` 会消耗所选账号的推理额度。** 未指定 `--account` 时检测 env 内的全部账号，
最多同时检测 3 个账号，每账号 3 次独立挑战并发执行，合计最多 9 路并发；无需新增命令参数。
任一次挑战失败或有效整数不足时，取消该账号其余挑战，不对残缺结果评分；已发起的调用仍可能消耗额度。
不自动改型号或降低强度；按 Ctrl+C 会取消在途挑战并清理本地检测进程。
检测器不额外重试；Codex 运行时自身的连接恢复可能增加实际请求次数。
`--detect-timeout 300` 设置每次挑战超时秒数（默认 300），与查询额度的 `--timeout` 分开。
全部检测结束后再查询额度；单账号检测失败不影响其他账号。检测结果按完成顺序逐个保存，
最终面板和 JSON 仍按 env 账号顺序展示。

面板显示首选候选、Astra 的**库内概率**、有效回答数及检测时间；`--json` 增加 `model_check`。
结果摘要保存在 env 文件旁的 `*.model-checks.json`（例如 `codex.model-checks.json`），
按账号 ID 的 SHA-256 区分，不保存令牌、原始账号 ID 或模型回答，并已加入 Git 忽略。
普通查询会展示同型号、同推理强度、同指纹库版本的最近记录，不重新调用模型；请结合时间查看，
旧记录不代表当前会话。缓存损坏时提示并忽略，写入失败时仍显示本次结果。

该功能判断数字输出更像哪个候选，**不能证明模型身份、ultra 实际生效或能力是否下降**。
随包 ModelTrace 库包含 Astra，但不包含 `gpt-6.1-sol`；其他研究已发现两者难以靠数字指纹区分。
未收录型号也会得到一个最近候选，因此状态使用“最像目标（仅供参考）”或“最像其他候选（待复测）”，
不把概率当成“降智概率”。此库未针对 Codex `ultra` 做独立校准。
算法、数据版本及 MIT 许可见 [`_modeltrace/NOTICE.md`](sd_spider_utils/_modeltrace/NOTICE.md)。

## 常用函数

| 函数 | 说明 |
| --- | --- |
| `normalize_text(text)` | NFKC 规范化并压缩连续空白 |
| `normalize_obj(obj)` | 递归规范化字典、列表中的字符串 |
| `clean_text(text)` | 压缩空白并清理逗号前空格 |
| `contains_chinese(text)` | 判断是否包含汉字 |
| `contains_date(text)` | 判断是否包含年月日日期 |
| `extract_dates(text)` | 提取有效日期并返回 `datetime` 列表 |
| `get_text_bs4(html)` | 使用 BeautifulSoup 提取 HTML 文本 |
| `get_text_xpath(html)` | 使用 lxml 返回全部文本节点 |
| `get_text_scrapy(html)` | 使用 Scrapy Selector 提取文本 |
| `load_json_data(path)` | 读取 JSON/JSONL，统一返回列表 |
| `data2excel(data, path)` | 字典列表写入 Excel |
| `json2excel(path)` | JSON/JSONL 转换为同名 Excel |
| `request_with_requests_go(url)` | 使用 Chrome TLS 指纹发起 HTTP 请求 |
| `request_with_curl_cffi(url)` | 使用 curl_cffi 模拟浏览器指纹发起请求 |
| `fetch_text_with_browser(url)` | 浏览器打开页面，等待 Vercel 安全验证通过后返回正文 |
| `strtobool(value)` | 常见真假字符串转布尔值 |

```python
from sd_spider_utils import extract_dates, normalize_obj

data = normalize_obj({"标题": " Ａ  \n B "})
dates = extract_dates("发布于 2026年6月30日")
```

### requests-go 请求

```python
from sd_spider_utils import request_with_requests_go

response = request_with_requests_go(
    "https://research.com/rankings",
    headers=headers,
    proxy="http://127.0.0.1:7890",
)
print(response.text)
print(response.status_code)
```

### curl_cffi 请求

```python
from sd_spider_utils import request_with_curl_cffi

response = request_with_curl_cffi(
    "https://www.amazon.com/s",
    params={"k": "洗发水", "i": "aps"},
    headers={"Referer": "https://www.amazon.com/"},
    impersonate="chrome",
)
print(response.text)
print(response.status_code)
```

`impersonate="chrome"` 会使用当前安装版本支持的最新版 Chrome 指纹；
传入 `chrome120` 等值可固定版本，传入 `None` 则不启用浏览器指纹模拟。
启用指纹模拟时，建议只补充业务需要的请求头，避免手写的 User-Agent 或
`sec-ch-ua` 版本与 TLS 指纹不一致。

## DrissionPage 工具

安装 `drissionpage` extra 后可使用：

| 函数 | 说明 |
| --- | --- |
| `get_browser(browser_type)` | 获取按类型复用的浏览器 |
| `close_browser(browser_type)` | 关闭指定类型的浏览器 |
| `close_all_browsers()` | 关闭全部单例浏览器 |
| `save_page()` | 使用指定类型的单例浏览器保存网页或 PDF |
| `download_page()` | 下载资源，已存在时跳过 |
| `get_html_from_chrome()` | 获取渲染后 HTML，可等待指定接口 |
| `singleton()` | 可重置的线程安全单例装饰器 |

`BrowserManager` 以 `browser_type` 作为单例标识，同一类型首次创建时的配置会持续使用，
直到调用 `close_browser()`。不同配置应使用不同类型名：

```python
from DrissionPage import ChromiumOptions
from sd_spider_utils import close_all_browsers, save_page

proxy_options = ChromiumOptions().headless().auto_port()
proxy_options.set_proxy("http://127.0.0.1:7890")

try:
    save_page("https://example.com", browser_type="default")
    save_page(
        "https://example.com/report",
        browser_type="proxy",
        browser_options=proxy_options,
    )
finally:
    close_all_browsers()
```

## Scrapy 下载中间件

推荐只注册 `BackendRouterMiddleware`：

```python
DOWNLOADER_MIDDLEWARES = {
    "sd_spider_utils.middlewares.BackendRouterMiddleware": 950,
}
```

通过 `Request.meta["download_backend"]` 选择后端：

```python
yield scrapy.Request(
    url,
    meta={"download_backend": "requests_go"},
)
```

支持 `scrapy`、`requests_go`、`curl_cffi`、`dp`、`dp_listen` 和
`scrapling`。
监听接口时还需传入 `listen_path`：

```python
yield scrapy.Request(
    url,
    meta={
        "download_backend": "dp_listen",
        "listen_path": "/api/list",
    },
)
```

`TunnelProxyMiddleware` 只在 `request.meta["use_proxy"]` 为真时读取
`SD_PROXY_URL` 设置静态代理；动态代理可直接写入 `request.meta["proxy"]`。

常用设置：

| 设置 | 默认值 | 说明 |
| --- | --- | --- |
| `DOWNLOAD_TIMEOUT` | `30` | 第三方下载后端超时秒数 |
| `SD_DRISSION_HEADLESS` | `True` | DrissionPage 是否无头运行 |
| `SD_DRISSION_LOAD_MODE` | 空 | DrissionPage 加载模式 |
| `SD_REQUESTS_GO_VERIFY` | `True` | requests-go 是否校验证书 |
| `SD_CURL_CFFI_IMPERSONATE` | `chrome` | curl_cffi 使用的浏览器指纹 |
| `SD_CURL_CFFI_VERIFY` | `True` | curl_cffi 是否校验证书 |
| `SD_SCRAPLING_HEADLESS` | `True` | Scrapling 是否无头运行 |

## 开发检查

```bash
uv run --locked python -m unittest discover -s tests
uv run --locked black --check sd_spider_utils tests
uv run --locked flake8 --ignore=E501 sd_spider_utils tests
uv build
```


```bash
# 打标签之后自动发布
# 改 pyproject.toml: version = "1.0.8"
git add .
git commit -m "release 1.0.8"
git tag v1.0.8
git push origin main --tags
```
