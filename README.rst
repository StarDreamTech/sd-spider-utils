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
