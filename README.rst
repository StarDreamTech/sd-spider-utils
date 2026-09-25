sd_spider_utils
================

一个高效的 Python 爬虫工具库，提供解析、文本标准化等常用功能，助力快速开发爬虫项目。

安装
----

使用 pip 安装：

::

    pip install sd_spider_utils

Scrapy 中间件按需安装：

::

    pip install "sd_spider_utils[all]"

只使用某一个下载后端时，也可以安装 ``scrapy``、``requests-go``、
``curl-cffi``、``drissionpage`` 或 ``scrapling`` extra。Scrapling
首次使用还需要执行：

::

    scrapling install

开发环境（uv）
--------------

源码开发统一使用 uv，在项目根目录执行：

::

    uv sync --locked
    uv run --locked python -m unittest discover -s tests
    uv build

uv 按 ``.python-version`` 使用 Python 3.12，并创建 ``.venv``。
开发依赖在 ``pyproject.toml`` 的 ``dev`` 组中，锁定版本记录在 ``uv.lock``。
需要全部可选功能时执行 ``uv sync --locked --all-extras``，运行命令时也加上
``--all-extras``。更多开发命令见仓库 README.md。

Codex 用量查询
--------------

将仓库中的 ``codex.env.example`` 复制为 ``codex.env``，填入
``CODEX_ACCESS_TOKEN`` 和 ``CODEX_ACCOUNT_ID``，然后执行：

::

    sd-codex-usage --env codex.env
    sd-codex-usage --env codex.env --json

输出账号套餐、用量百分比、额度重置时间、查询时间，以及可用重置卡张数和每张卡的过期时间。
默认将所有账号合并为一张 Rich 彩色汇总表，按剩余额度用绿、黄、红提示，倒计时显示为天、小时、分、秒。
``--json`` 保留原始数值及 ISO 时间格式。
命令仅发送 GET 请求查询信息，不会使用或兑换重置卡。过期时间缺失时显示未知。
多账号使用 ``CODEX_名称_ACCESS_TOKEN`` / ``CODEX_名称_ACCOUNT_ID`` 成对配置。
也支持 ``CODEX_ACCESS_TOKEN_名称`` / ``CODEX_ACCOUNT_ID_名称``，名称区分大小写。
``--encode`` / ``--decode`` 支持 ``base64rev:`` 前缀的 Base64 倒序混淆；
混淆不是加密。仅支持 ChatGPT 登录凭据，不支持普通 API Key。
详细格式、错误处理和 PyCharm 配置见仓库 README.md。

使用示例
--------

::

    from sd_spider_utils.text_utils import normalize_text

    text = "Ｃａｆé['S.\u2009M. Koksbang\xa0', 'S.\u2009M. Koksbang']"  # 包含全角字符和组合字符
    clean_text = normalize_text(text)
    print(clean_text)

Scrapy 下载中间件
-----------------

推荐只注册统一路由中间件：

::

    DOWNLOADER_MIDDLEWARES = {
        "sd_spider_utils.middlewares.BackendRouterMiddleware": 950,
    }

    yield scrapy.Request(
        url,
        meta={"download_backend": "requests_go"},
    )

可选后端为 ``scrapy``、``requests_go``、``curl_cffi``、``dp``、
``dp_listen`` 和 ``scrapling``。

监听接口时使用 ``download_backend="dp_listen"``，并通过
``listen_path`` 设置需要等待的接口路径。

静态代理可在路由中间件之前注册：

::

    DOWNLOADER_MIDDLEWARES = {
        "sd_spider_utils.middlewares.TunnelProxyMiddleware": 740,
        "sd_spider_utils.middlewares.BackendRouterMiddleware": 950,
    }
    SD_PROXY_URL = "http://127.0.0.1:7890"

只有 ``request.meta["use_proxy"]`` 为真时才会补充 ``SD_PROXY_URL``；
请求里已有 ``proxy`` 时不会覆盖。

功能特性
--------

- **HTML 解析**：快速提取网页中的文本内容。
- **文本标准化**：清洗和规范化抓取到的文本数据。
- **常用工具函数**：提供日期提取、数据转换和多种下载后端。

项目链接
--------

- PyPI: https://pypi.org/project/sd_spider_utils/
- 源码仓库: https://github.com/StarDreamTech/sd_spider_utils
- 视频教程:  https://space.bilibili.com/1909782963
- 作者: 星梦 (cpython666@gmail.com)

许可证
------

MIT License，详见 LICENSE 文件。
