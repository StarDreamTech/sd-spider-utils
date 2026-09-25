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

## Codex 用量命令

开发目录先执行 `python -m pip install -e .`，然后复制根目录的
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
sd-codex-usage --env codex.env
sd-codex-usage --env "D:/private/codex.env" --json --timeout 20
# 不安装命令入口时，在项目根目录执行：
python -m sd_spider_utils.codex_usage --env codex.env
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
更新旧环境时执行 `python -m pip install -e .` 安装新增的 Rich 依赖。
同时显示可用重置卡张数、每张返回卡片的状态和过期时间（本地时区）。
张数以服务端 `available_count` 为准，明细可能只返回部分卡片，不能用列表长度代替。
未提供过期时间显示“未知”，不推断为永不过期；未提供张数也不当作 0。
JSON 中对应 `rate_limit_reset_credits`，包含 `available_count` 和 `credits`。
明细查询失败时保留用量及用量接口给出的张数，并输出 `reset_credits_error`。
缺失字段显示“未知”，不会当作零用量，也不会推算固定 Token 总配额。
每次运行重新查询；不修改 env、不刷新登录令牌。单账号失败不影响其他账号查询。
退出码：`0` 全部成功，`1` 至少一个账号的用量或重置卡明细查询失败，`2` 参数或 env 配置错误。

支持 UTF-8（含 BOM）、空行、注释、`export KEY=VALUE` 和单行单/双引号；
不执行 shell 表达式，不展开 `${变量}`，不读取其他环境变量中的账号凭据。
未加引号的值在“空白 + #”处开始注释。不支持多行值及引号内的转义。

需要沿用 Base64 后倒序的混淆格式时：

```bash
sd-codex-usage --encode  # 隐藏输入，输出 base64rev: 前缀的完整值
sd-codex-usage --decode # 隐藏输入，解码带前缀的值
```

把生成的完整值填入任一账号字段即可。已有的无前缀倒序 Base64 值需手动
补上 `base64rev:`。这是可逆混淆，不是加密；真实 `.env` / `*.env` 已加入
Git 忽略规则，勿提交凭据；编码、解码命令会把结果打印到终端。

命令只发出 GET 请求，固定访问以下两个只读接口：

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
`--env D:/private/codex.env`，解释器选择已安装本项目的环境。

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
python -m unittest discover -s tests
black --check sd_spider_utils tests
flake8 --ignore=E501 sd_spider_utils tests
```


```bash
# 打标签之后自动发布
# 改 pyproject.toml: version = "1.0.8"
git add .
git commit -m "release 1.0.8"
git tag v1.0.8
git push origin main --tags
```
