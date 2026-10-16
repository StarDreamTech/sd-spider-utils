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

Steam 评测导出
--------------

安装包含此功能的版本后直接使用，无需 Steam 登录、Cookie、API Key 或数据库：

::

    sd-steam-reviews --appid 246420 --language schinese
    sd-steam-reviews --kingdom-rush 1 --language all
    sd-steam-reviews --appid 246420 --output "./data/reviews.jl"
    sd-steam-reviews --help
    python -m sd_spider_utils.steam_reviews --appid 246420

每次采集一个游戏；``--kingdom-rush`` 支持 1～5 代，默认语言为简体中文。
预览总数和预计请求量后，直接按回车开始，输入其他内容或结束输入则取消。
默认输出当前目录下 ``steam_reviews/<appid>_<language>.jl``，每行是完整评测 JSON，
附加游戏、查询语言和 UTC 抓取时间；成功后保存同名 ``.jl.state.json``。
请保留这两个文件，避免两个任务同时写同一文件。

默认 ``--mode auto`` 首次完整初始化，之后按时间边界增量采集并按 ID 去重。
``--mode init`` 拒绝覆盖非空文件；``--mode incremental`` 要求已有数据文件；
缺少成功状态时先去重补齐初始化。``--mode full`` 可全历史去重补采。
增量不覆盖旧评测的修改，不删除已保存内容；失败不推进成功边界，重跑即可补采。
``--page-size`` 支持 1～100，默认 100；``--interval`` 默认 1 秒且至少 1 秒。

使用 Steam 官方公开 GetAppReviews 接口，仅采集公开可返回的评测。
匿名响应可能缓存最多 10 分钟；临时错误有限重试，长时间限流退出并保留进度。
退出码：0 成功或取消，1 采集失败，2 参数错误，130 用户中断。

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
默认额度查询仅发送 GET 请求，不会使用或兑换重置卡。过期时间缺失时显示未知。
额度和重置卡查询遇到网络错误或 HTTP 408/429/500/502/503/504，最多额外重试三次，
含首次共最多四次请求，默认等待 1、2、4 秒；遵守 ``Retry-After``，超过 60 秒则提示稍后查询。
401/403 及无效 JSON 不重试；``--timeout`` 默认每次请求 30 秒。重试进度输出到 stderr。
多账号使用 ``CODEX_名称_ACCESS_TOKEN`` / ``CODEX_名称_ACCOUNT_ID`` 成对配置。
也支持 ``CODEX_ACCESS_TOKEN_名称`` / ``CODEX_ACCOUNT_ID_名称``，名称区分大小写。
``--encode`` / ``--decode`` 支持 ``base64rev:`` 前缀的 Base64 倒序混淆；
混淆不是加密。仅支持 ChatGPT 登录凭据，不支持普通 API Key。
详细格式、错误处理和 PyCharm 配置见仓库 README.md。

可选模型指纹检测固定使用 Codex 订阅、``gpt-6-astra`` 和 ``ultra``。
需要 Codex CLI 及 ``model-check`` 可选依赖。优先查找 PATH；macOS 也会自动查找
``/Applications`` 或 ``~/Applications`` 中 ChatGPT.app 内置的 CLI：

::

    uv run --locked --extra model-check sd-codex-usage --env codex.env --detect
    uv run --locked --extra model-check sd-codex-usage --env codex.env --detect --account WORK

最多同时检测三个账号，每账号三次独立挑战并发执行，合计最多九路并发，会消耗推理额度。
单次挑战失败会取消同账号其余挑战；Ctrl+C 会取消在途挑战并清理本地进程。
``--detect-timeout`` 控制每次挑战超时（默认 300 秒）。结果逐个保存，最终仍按 env 账号顺序展示。
通过独立的 Codex app-server 使用 env 对应账号，保留 ``ultra`` 由客户端处理。
结果缓存在 env 旁的 ``*.model-checks.json``，普通查询仅展示上次结果，不再生成挑战。
缓存不包含登录令牌、原始账号 ID 或模型回答。指纹库内概率不是降智概率，
不能证明模型身份或推理强度实际生效；Astra 与 6.1 Sol 可能无法据此区分。

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
