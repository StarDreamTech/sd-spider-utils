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
pip install "sd_spider_utils[drissionpage]" # Scrapy + DrissionPage
pip install "sd_spider_utils[scrapling]"    # Scrapy + Scrapling
pip install "sd_spider_utils[all]"          # 安装全部可选功能
```

Scrapling 首次使用还需执行 `scrapling install` 下载浏览器。

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

支持 `scrapy`、`requests_go`、`drission`、`drission_listen` 和 `scrapling`。
监听接口时还需传入 `listen_path`：

```python
yield scrapy.Request(
    url,
    meta={
        "download_backend": "drission_listen",
        "listen_path": "/api/list",
    },
)
```

显式配置 `backend_fallbacks` 后，403、429、503 或常见 Cloudflare
挑战页会切换到下一个后端：

```python
meta={"backend_fallbacks": ["scrapy", "requests_go", "scrapling"]}
```

`TunnelProxyMiddleware` 可读取 `SD_PROXY_URL` 设置静态代理；动态代理直接写入
`request.meta["proxy"]`，由 Scrapy 内置代理中间件处理。

常用设置：

| 设置 | 默认值 | 说明 |
| --- | --- | --- |
| `DOWNLOAD_TIMEOUT` | `30` | 第三方下载后端超时秒数 |
| `SD_DRISSION_HEADLESS` | `True` | DrissionPage 是否无头运行 |
| `SD_DRISSION_LOAD_MODE` | 空 | DrissionPage 加载模式 |
| `SD_REQUESTS_GO_VERIFY` | `True` | requests-go 是否校验证书 |
| `SD_SCRAPLING_HEADLESS` | `True` | Scrapling 是否无头运行 |
| `SD_SCRAPLING_SESSION_OPTIONS` | `{}` | Scrapling Session 参数 |

## 开发检查

```bash
python -m unittest discover -s tests
black --check sd_spider_utils tests
flake8 --ignore=E501 sd_spider_utils tests
```


```bash
# 打标签之后自动发布
# 改 pyproject.toml: version = "1.0.3"
git add .
git commit -m "release 1.0.6"
git tag v1.0.6
git push origin main --tags
```
