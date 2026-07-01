"""Scrapy 下载中间件。

通过 request.meta["download_backend"] 选择 requests_go、dp、dp_listen
或 scrapling；不设置时继续使用 Scrapy 默认下载器。
"""

from __future__ import annotations

import json
import logging

from scrapy import signals
from scrapy.exceptions import NotConfigured, NotSupported
from scrapy.http import Headers, HtmlResponse, Request
from twisted.internet.threads import deferToThread

logger = logging.getLogger(__name__)

BACKEND_META_KEY = "download_backend"
SUPPORTED_BACKENDS = {"scrapy", "requests_go", "dp", "dp_listen", "scrapling"}
_BROWSER_BACKENDS = {"dp", "dp_listen", "scrapling"}
# 重新包装 HtmlResponse 时移除可能失真的传输类响应头。
_DROP_RESPONSE_HEADERS = {"content-encoding", "content-length", "transfer-encoding"}


def _backend_for_request(request: Request) -> str | None:
    """读取并检查请求指定的下载后端。

    :param request: Scrapy Request
    :return: 下载后端名称；未设置时返回 None
    """
    backend = request.meta.get(BACKEND_META_KEY)
    if backend is None:
        return None
    backend = str(backend).strip().lower()
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"不支持的下载后端：{backend!r}")
    return backend


def _request_timeout(request: Request, default: float) -> float:
    """获取请求超时秒数。

    :param request: Scrapy Request
    :param default: 默认超时秒数
    :return: 大于零的超时秒数
    """
    timeout = float(request.meta.get("download_timeout", default))
    if timeout <= 0:
        raise ValueError("download_timeout 必须大于 0")
    return timeout


def _request_headers(request: Request) -> dict[str, str]:
    """把 Scrapy 请求头转换为普通字典。"""
    ignored = {"content-length", "host"}
    return {
        key: value
        for key, value in request.headers.to_unicode_dict().items()
        if key.lower() not in ignored
    }


def _build_response(
    request: Request,
    body,
    status=200,
    url=None,
    headers=None,
    backend=None,
) -> HtmlResponse:
    """把第三方下载结果转换为 Scrapy HtmlResponse。

    :param request: 原始 Scrapy Request
    :param body: 响应正文
    :param status: HTTP 状态码
    :param url: 最终响应地址
    :param headers: 响应头
    :param backend: 下载后端名称
    :return: Scrapy HtmlResponse
    """
    response_headers = Headers(headers or {})
    for name in _DROP_RESPONSE_HEADERS:
        response_headers.pop(name, None)

    encoding = None
    if isinstance(body, (dict, list)):
        body = json.dumps(body, ensure_ascii=False)
        response_headers.setdefault("Content-Type", "application/json; charset=utf-8")
    if isinstance(body, str):
        body = body.encode()
        encoding = "utf-8"
    elif isinstance(body, bytearray):
        body = bytes(body)
    elif not isinstance(body, bytes):
        body = str(body or "").encode()
        encoding = "utf-8"

    return HtmlResponse(
        url=url or request.url,
        status=int(status),
        headers=response_headers,
        body=body,
        encoding=encoding,
        request=request,
        flags=[f"download-backend:{backend}"] if backend else None,
    )


class BackendRouterMiddleware:
    """根据 download_backend 把请求交给对应的下载函数。"""

    def __init__(self, crawler):
        self.settings = crawler.settings
        self.timeout = self.settings.getfloat("DOWNLOAD_TIMEOUT", 10)
        self._browser_types = set()

    @classmethod
    def from_crawler(cls, crawler):
        """创建中间件，并在 Spider 关闭时释放浏览器。"""
        middleware = cls(crawler)
        crawler.signals.connect(middleware.spider_closed, signal=signals.spider_closed)
        return middleware

    def process_request(self, request: Request, spider=None):
        """异步执行请求选择的第三方下载后端。"""
        backend = _backend_for_request(request)
        if not backend or backend == "scrapy":
            return None
        if backend in _BROWSER_BACKENDS and request.method != "GET":
            raise NotSupported(f"{backend} 仅支持 GET 请求")

        download = {
            "requests_go": self._download_requests_go,
            "dp": self._download_dp,
            "dp_listen": self._download_dp_listen,
            "scrapling": self._download_scrapling,
        }[backend]
        return deferToThread(download, request, _request_timeout(request, self.timeout))

    def _download_requests_go(self, request: Request, timeout: float):
        """使用 requests-go 下载请求。"""
        from .request_utils import request_with_requests_go

        options = {
            "method": request.method,
            "headers": _request_headers(request),
            "proxy": request.meta.get("proxy"),
            "timeout": timeout,
            "allow_redirects": False,
            "verify": request.meta.get(
                "verify",
                self.settings.getbool("SD_REQUESTS_GO_VERIFY", True),
            ),
        }
        if request.body:
            options["data"] = request.body
        response = request_with_requests_go(request.url, **options)
        return _build_response(
            request,
            response.content,
            response.status_code,
            response.url,
            response.headers,
            "requests_go",
        )

    def _get_browser(self, request: Request):
        """按代理和配置复用 dp_utils 中的单例浏览器。"""
        from DrissionPage import ChromiumOptions

        from .dp_utils import get_browser

        proxy = request.meta.get("proxy") or ""
        headless = self.settings.getbool("SD_DRISSION_HEADLESS", True)
        load_mode = self.settings.get("SD_DRISSION_LOAD_MODE") or ""
        browser_type = f"scrapy-dp:{proxy or 'direct'}:{headless}:{load_mode}"

        options = ChromiumOptions().auto_port().headless(headless)
        if load_mode:
            options.set_load_mode(load_mode)
        if proxy:
            options.set_proxy(proxy)

        self._browser_types.add(browser_type)
        return get_browser(browser_type, options)

    def _download_dp(self, request: Request, timeout: float):
        """使用 DrissionPage 获取渲染后的页面。"""
        tab = self._get_browser(request).new_tab()
        try:
            tab.get(request.url, timeout=timeout)
            return _build_response(request, tab.html, url=tab.url, backend="dp")
        finally:
            tab.close()

    def _download_dp_listen(self, request: Request, timeout: float):
        """使用 DrissionPage 获取指定接口的响应。"""
        listen_path = request.meta.get("listen_path")
        if not listen_path:
            raise ValueError("dp_listen 必须设置 listen_path")

        tab = self._get_browser(request).new_tab()
        try:
            tab.listen.start(listen_path)
            tab.get(request.url, timeout=timeout)
            packet = tab.listen.wait(timeout=timeout, raise_err=False)
            if not packet or not packet.response:
                raise TimeoutError(f"等待接口 {listen_path!r} 超时")
            response = packet.response
            body = response.raw_body
            if body is None:
                body = response.body
            return _build_response(
                request,
                body,
                response.status,
                packet.url,
                response.headers,
                "dp_listen",
            )
        finally:
            tab.close()

    def _download_scrapling(self, request: Request, timeout: float):
        """使用 Scrapling StealthyFetcher 下载页面。"""
        from scrapling.fetchers import StealthyFetcher

        options = dict(request.meta.get("scrapling_options") or {})
        options.setdefault(
            "headless",
            self.settings.getbool("SD_SCRAPLING_HEADLESS", True),
        )
        options.setdefault("solve_cloudflare", False)
        options["timeout"] = timeout * 1000
        options["extra_headers"] = _request_headers(request)
        if proxy := request.meta.get("proxy"):
            options["proxy"] = proxy

        page = StealthyFetcher.fetch(request.url, **options)
        return _build_response(
            request,
            page.body,
            page.status,
            page.url,
            page.headers,
            "scrapling",
        )

    def spider_closed(self, spider=None, reason=None):
        """Spider 关闭时异步释放全部浏览器。"""
        return deferToThread(self._close_browsers)

    def _close_browsers(self):
        from .dp_utils import close_browser

        browser_types, self._browser_types = self._browser_types, set()
        for browser_type in browser_types:
            try:
                close_browser(browser_type)
            except Exception:
                logger.debug("关闭浏览器失败", exc_info=True)


class TunnelProxyMiddleware:
    """请求显式启用代理时，补充 SD_PROXY_URL。"""

    def __init__(self, proxy_url: str):
        self.proxy_url = proxy_url

    @classmethod
    def from_crawler(cls, crawler):
        """读取 SD_PROXY_URL；未配置时禁用中间件。"""
        proxy_url = crawler.settings.get("SD_PROXY_URL")
        if not proxy_url:
            raise NotConfigured("未配置 SD_PROXY_URL")
        return cls(proxy_url)

    def process_request(self, request: Request, spider=None):
        """use_proxy 为真时设置代理；已传 proxy 时不覆盖。"""
        if not request.meta.get("use_proxy"):
            return None
        request.meta.setdefault("proxy", self.proxy_url)
