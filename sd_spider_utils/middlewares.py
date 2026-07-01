from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from time import monotonic
from typing import Any

from scrapy import signals
from scrapy.exceptions import (
    DownloadFailedError,
    DownloadTimeoutError,
    NotConfigured,
    NotSupported,
)
from scrapy.http import Headers, Request, Response
from scrapy.responsetypes import responsetypes
from twisted.internet.defer import Deferred, DeferredList
from twisted.internet.threads import deferToThread, deferToThreadPool
from twisted.python.threadpool import ThreadPool

logger = logging.getLogger(__name__)

BACKEND_META_KEY = "download_backend"
BACKEND_FALLBACKS_META_KEY = "backend_fallbacks"
_BACKEND_INDEX_META_KEY = "_sd_backend_index"
_SUPPORTED_BACKENDS = {
    "scrapy",
    "requests_go",
    "drission",
    "drission_listen",
    "scrapling",
}
_BROWSER_BACKENDS = {"drission", "drission_listen", "scrapling"}
_FALLBACK_STATUSES = {403, 429, 503}
_CHALLENGE_MARKERS = (
    b"<title>just a moment",
    b"/cdn-cgi/challenge-platform/",
    b"cf-chl-",
)
_DROP_REQUEST_HEADERS = {
    "connection",
    "content-length",
    "host",
    "proxy-connection",
    "transfer-encoding",
}
_DROP_RESPONSE_HEADERS = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
}


def _normalize_backend(value: Any) -> str | None:
    if value is None:
        return None
    backend = str(value).strip().lower()
    if backend not in _SUPPORTED_BACKENDS:
        raise ValueError(f"不支持的下载后端：{value!r}")
    return backend


def _fallback_backends(request: Request) -> list[str]:
    values = request.meta.get(BACKEND_FALLBACKS_META_KEY) or []
    if isinstance(values, str):
        values = values.split(",")
    backends = []
    for value in values:
        value = value.strip() if isinstance(value, str) else value
        if value:
            backends.append(_normalize_backend(value))
    return backends


def _backend_for_request(request: Request) -> str | None:
    backend = _normalize_backend(request.meta.get(BACKEND_META_KEY))
    if backend:
        return backend

    fallbacks = _fallback_backends(request)
    if fallbacks:
        return fallbacks[int(request.meta.get(_BACKEND_INDEX_META_KEY, 0))]
    return None


def _request_timeout(request: Request, default: float) -> float:
    try:
        timeout = float(request.meta.get("download_timeout", default))
    except (TypeError, ValueError) as exc:
        raise ValueError("download_timeout 必须是数字") from exc
    if timeout <= 0:
        raise ValueError("download_timeout 必须大于 0")
    return timeout


def _request_headers(request: Request, *, browser: bool = False) -> dict[str, str]:
    headers = dict(request.headers.to_unicode_dict())
    dropped = _DROP_REQUEST_HEADERS | ({"cookie", "user-agent"} if browser else set())
    return {key: value for key, value in headers.items() if key.lower() not in dropped}


def _request_cookies(request: Request) -> list[dict[str, str]]:
    raw = request.headers.get("Cookie")
    if not raw:
        return []
    cookies = []
    for item in raw.decode("latin-1").split(";"):
        name, separator, value = item.strip().partition("=")
        if name and separator:
            cookies.append({"name": name, "value": value, "url": request.url})
    return cookies


def _response_headers(headers: Any, cookies: Any = None) -> Headers:
    result = Headers(headers or {})
    for name in _DROP_RESPONSE_HEADERS:
        result.pop(name, None)
    if not cookies:
        return result

    if isinstance(cookies, dict):
        cookies = (
            [cookies]
            if "name" in cookies
            else [{"name": key, "value": value} for key, value in cookies.items()]
        )
    existing = {
        value.decode("latin-1").partition("=")[0].lower()
        for value in result.getlist("Set-Cookie")
    }
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = cookie.get("name") or cookie.get("Name")
        if not name or name.lower() in existing:
            continue
        value = cookie.get("value", cookie.get("Value", ""))
        parts = [f"{name}={value}"]
        for lower, upper in (("domain", "Domain"), ("path", "Path")):
            if item := cookie.get(lower) or cookie.get(upper):
                parts.append(f"{upper}={item}")
        if cookie.get("secure") or cookie.get("Secure"):
            parts.append("Secure")
        if cookie.get("httpOnly") or cookie.get("HttpOnly"):
            parts.append("HttpOnly")
        result.appendlist("Set-Cookie", "; ".join(parts))
        existing.add(name.lower())
    return result


def _scrapy_response(
    request: Request,
    backend: str,
    url: str | None,
    status: Any,
    headers: Any,
    body: Any,
    cookies: Any = None,
) -> Response:
    """把第三方下载结果转换成保留状态和响应头的 Scrapy Response。"""
    response_headers = _response_headers(headers, cookies)
    if isinstance(body, (dict, list)):
        response_headers.setdefault("Content-Type", "application/json; charset=utf-8")
        body = json.dumps(body, ensure_ascii=False)
    if isinstance(body, str):
        content_type = response_headers.get("Content-Type", b"text/html").decode(
            "latin-1"
        )
        media_type = content_type.partition(";")[0]
        response_headers["Content-Type"] = media_type + "; charset=utf-8"
        body = body.encode()
    elif isinstance(body, bytearray):
        body = bytes(body)
    elif not isinstance(body, bytes):
        body = str(body or "").encode()
    try:
        status = int(status)
    except (TypeError, ValueError) as exc:
        raise DownloadFailedError(f"{backend} 返回了无效状态码：{status!r}") from exc
    if not 100 <= status <= 599:
        raise DownloadFailedError(f"{backend} 返回了无效状态码：{status!r}")

    url = url or request.url
    response_class = responsetypes.from_args(
        headers=response_headers,
        url=url,
        body=body,
    )
    return response_class(
        url=url,
        status=status,
        headers=response_headers,
        body=body,
        request=request,
        flags=[f"download-backend:{backend}"],
    )


def _backend_error(backend: str, exception: Exception) -> Exception:
    if isinstance(
        exception,
        (DownloadFailedError, DownloadTimeoutError, NotSupported, ImportError),
    ):
        return exception
    text = f"{exception.__class__.__name__} {exception}".lower()
    error_class = (
        DownloadTimeoutError
        if "timeout" in text or "timed out" in text or "超时" in text
        else DownloadFailedError
    )
    return error_class(f"{backend} 下载失败：{exception}")


def _close(resource: Any, method: str) -> None:
    if resource is None:
        return
    try:
        getattr(resource, method)()
    except Exception:
        logger.debug("关闭资源失败", exc_info=True)


class _DrissionBrowsers:
    """为一个 crawler 按代理和 cookiejar 隔离浏览器。"""

    def __init__(self, headless: bool, load_mode: str | None):
        self.headless = headless
        self.load_mode = load_mode
        self._items = {}
        self._lock = threading.Lock()

    def get(self, request: Request):
        key = (
            request.meta.get("proxy") or "",
            str(request.meta.get("cookiejar", "default")),
        )
        with self._lock:
            # ponytail: 缓存到 spider 结束；代理数量明显失控时再加 LRU。
            if key not in self._items:
                from DrissionPage import Chromium, ChromiumOptions

                options = ChromiumOptions().auto_port().headless(self.headless)
                if self.load_mode:
                    options.set_load_mode(self.load_mode)
                if key[0]:
                    options.set_proxy(key[0])
                self._items[key] = Chromium(options)
            return key, self._items[key]

    def discard(self, key) -> None:
        with self._lock:
            browser = self._items.pop(key, None)
        _close(browser, "quit")

    def close(self) -> None:
        with self._lock:
            browsers, self._items = list(self._items.values()), {}
        for browser in browsers:
            _close(browser, "quit")


class BackendRouterMiddleware:
    """根据 Request.meta 选择 requests-go、DrissionPage 或 Scrapling。"""

    def __init__(self, crawler):
        self.crawler = crawler
        self.settings = crawler.settings
        self.default_timeout = self.settings.getfloat("DOWNLOAD_TIMEOUT", 30)
        self.browsers = _DrissionBrowsers(
            self.settings.getbool("SD_DRISSION_HEADLESS", True),
            self.settings.get("SD_DRISSION_LOAD_MODE"),
        )
        self.scrapling_pool = None
        self.scrapling_sessions = {}

    @classmethod
    def from_crawler(cls, crawler):
        """从 Scrapy crawler 创建中间件并注册资源清理。"""
        middleware = cls(crawler)
        crawler.signals.connect(middleware.spider_closed, signal=signals.spider_closed)
        return middleware

    def process_request(self, request: Request) -> Deferred | None:
        """把显式选择第三方后端的请求移交给对应下载器。"""
        backend = _backend_for_request(request)
        if not backend or backend == "scrapy":
            return None
        if backend in _BROWSER_BACKENDS and request.method != "GET":
            raise NotSupported(f"{backend} 仅支持 GET 请求")

        timeout = _request_timeout(request, self.default_timeout)
        if backend == "scrapling":
            if self.scrapling_pool is None:
                # ponytail: Playwright 同步会话固定在一个线程；需要并发时改异步会话。
                self.scrapling_pool = ThreadPool(
                    minthreads=1,
                    maxthreads=1,
                    name="sd-scrapling",
                )
                self.scrapling_pool.start()
            from twisted.internet import reactor

            return deferToThreadPool(
                reactor,
                self.scrapling_pool,
                self._download,
                backend,
                request,
                timeout,
            )
        # ponytail: requests-go/DrissionPage 共用 Twisted 线程池；阻塞被观测到再拆池。
        return deferToThread(self._download, backend, request, timeout)

    def process_response(
        self, request: Request, response: Response
    ) -> Request | Response:
        """命中反爬状态时，按 backend_fallbacks 切换到下一个后端。"""
        backends = _fallback_backends(request)
        index = int(request.meta.get(_BACKEND_INDEX_META_KEY, 0))
        if not backends or index + 1 >= len(backends):
            return response
        challenged = any(
            marker in response.body[:65536].lower() for marker in _CHALLENGE_MARKERS
        )
        if response.status not in _FALLBACK_STATUSES and not challenged:
            return response

        meta = request.meta.copy()
        meta[_BACKEND_INDEX_META_KEY] = index + 1
        meta[BACKEND_META_KEY] = backends[index + 1]
        logger.warning("下载后端降级：%s -> %s", backends[index], backends[index + 1])
        return request.replace(meta=meta, dont_filter=True)

    def _download(self, backend: str, request: Request, timeout: float) -> Response:
        try:
            return getattr(self, f"_download_{backend}")(request, timeout)
        except Exception as exc:
            normalized = _backend_error(backend, exc)
            if normalized is exc:
                raise
            raise normalized from exc

    def _download_requests_go(self, request: Request, timeout: float) -> Response:
        import requests_go

        proxy = request.meta.get("proxy")
        kwargs = {
            "method": request.method,
            "url": request.url,
            "headers": _request_headers(request),
            "timeout": timeout,
            "allow_redirects": False,
            "proxies": {"http": proxy, "https": proxy} if proxy else None,
            "verify": request.meta.get(
                "verify",
                self.settings.getbool("SD_REQUESTS_GO_VERIFY", True),
            ),
            "tls_config": requests_go.tls_config.TLS_CHROME_LATEST,
        }
        if request.body:
            kwargs["data"] = request.body
        response = requests_go.request(**kwargs)
        return _scrapy_response(
            request,
            "requests_go",
            response.url,
            response.status_code,
            response.headers,
            response.content,
        )

    @staticmethod
    def _prepare_tab(tab, request: Request) -> None:
        if user_agent := request.headers.get("User-Agent"):
            tab.set.user_agent(user_agent.decode("latin-1"))
        if headers := _request_headers(request, browser=True):
            tab.set.headers(headers)
        if cookies := _request_cookies(request):
            tab.set.cookies(cookies)

    @contextmanager
    def _tab(self, request: Request):
        key, browser = self.browsers.get(request)
        try:
            tab = browser.new_tab()
        except Exception:
            self.browsers.discard(key)
            _, browser = self.browsers.get(request)
            tab = browser.new_tab()
        try:
            self._prepare_tab(tab, request)
            yield tab
        finally:
            _close(tab, "close")

    @staticmethod
    def _document_packet(tab, timeout: float):
        packets = []
        packet = tab.listen.wait(timeout=min(timeout, 0.5), raise_err=False)
        while packet:
            packets.append(packet)
            packet = tab.listen.wait(timeout=0.05, raise_err=False)
        final_url = str(tab.url).rstrip("/")
        return next(
            (
                item
                for item in reversed(packets)
                if str(item.url).rstrip("/") == final_url
            ),
            packets[-1] if packets else None,
        )

    def _download_drission(self, request: Request, timeout: float) -> Response:
        with self._tab(request) as tab:
            started = monotonic()
            tab.listen.start(targets=True, method="GET", res_type="Document")
            tab.get(request.url, timeout=timeout)
            packet = self._document_packet(
                tab,
                max(0.05, timeout - (monotonic() - started)),
            )
            if not packet or not packet.response:
                raise DownloadFailedError("未取得主文档响应")
            packet.wait_extra_info(timeout=0.2)
            return _scrapy_response(
                request,
                "drission",
                tab.url,
                packet.response.status,
                packet.response.headers,
                tab.html,
                tab.cookies(all_domains=False, all_info=True),
            )

    def _download_drission_listen(
        self,
        request: Request,
        timeout: float,
    ) -> Response:
        target = request.meta.get("listen_path")
        if not target:
            raise ValueError("drission_listen 必须设置 listen_path")
        with self._tab(request) as tab:
            started = monotonic()
            tab.listen.start(target)
            tab.get(request.url, timeout=timeout)
            remaining = timeout - (monotonic() - started)
            packet = (
                tab.listen.wait(timeout=remaining, raise_err=False)
                if remaining > 0
                else None
            )
            if not packet or not packet.response:
                raise DownloadTimeoutError(f"等待接口 {target!r} 超时")
            packet.wait_extra_info(timeout=0.2)
            return _scrapy_response(
                request,
                "drission_listen",
                packet.url,
                packet.response.status,
                packet.response.headers,
                (
                    packet.response.raw_body
                    if packet.response.raw_body is not None
                    else packet.response.body
                ),
                tab.cookies(all_domains=False, all_info=True),
            )

    def _scrapling_session(self, request: Request):
        key = (
            request.meta.get("proxy") or "",
            str(request.meta.get("cookiejar", "default")),
        )
        if key not in self.scrapling_sessions:
            from scrapling.fetchers import StealthySession

            options = self.settings.getdict("SD_SCRAPLING_SESSION_OPTIONS")
            options.setdefault(
                "headless",
                self.settings.getbool("SD_SCRAPLING_HEADLESS", True),
            )
            options.setdefault("solve_cloudflare", False)
            options.setdefault("retries", 1)
            if key[0]:
                options["proxy"] = key[0]
            session = StealthySession(**options)
            session.start()
            # ponytail: 按会话键缓存；代理无限增长时再加上限。
            self.scrapling_sessions[key] = session
        return self.scrapling_sessions[key]

    def _download_scrapling(self, request: Request, timeout: float) -> Response:
        options = dict(request.meta.get("scrapling_options") or {})
        options["timeout"] = timeout * 1000
        options.setdefault(
            "solve_cloudflare",
            bool(request.meta.get("solve_cloudflare")),
        )
        options["extra_headers"] = {
            **_request_headers(request),
            **dict(options.get("extra_headers") or {}),
        }
        if request.headers.get("Referer"):
            options.setdefault("google_search", False)

        cookies = _request_cookies(request)
        page_setup = options.get("page_setup")
        if cookies:

            def setup(page):
                page.context.add_cookies(cookies)
                if page_setup:
                    page_setup(page)

            options["page_setup"] = setup

        page = self._scrapling_session(request).fetch(request.url, **options)
        return _scrapy_response(
            request,
            "scrapling",
            page.url,
            page.status,
            page.headers,
            page.body,
            page.cookies,
        )

    def _close_scrapling(self) -> None:
        sessions, self.scrapling_sessions = self.scrapling_sessions.values(), {}
        for session in sessions:
            _close(session, "close")

    def spider_closed(self, spider, reason) -> Deferred:
        """Spider 关闭时释放浏览器和 Scrapling 会话。"""
        deferreds = [deferToThread(self.browsers.close)]
        if self.scrapling_pool and self.scrapling_sessions:
            from twisted.internet import reactor

            deferreds.append(
                deferToThreadPool(
                    reactor,
                    self.scrapling_pool,
                    self._close_scrapling,
                )
            )
        result = DeferredList(deferreds, consumeErrors=True)
        result.addBoth(self._stop_scrapling_pool)
        return result

    def _stop_scrapling_pool(self, result):
        if self.scrapling_pool:
            self.scrapling_pool.stop()
            self.scrapling_pool = None
        return result


class TunnelProxyMiddleware:
    """为未设置代理的请求补充 SD_PROXY_URL 静态代理。"""

    def __init__(self, proxy_url: str):
        self.proxy_url = proxy_url

    @classmethod
    def from_crawler(cls, crawler):
        """读取 SD_PROXY_URL；未配置时禁用中间件。"""
        proxy_url = crawler.settings.get("SD_PROXY_URL")
        if not proxy_url:
            raise NotConfigured("未配置 SD_PROXY_URL")
        return cls(proxy_url)

    def process_request(self, request: Request) -> None:
        """保留请求自带代理，否则使用静态代理。"""
        request.meta.setdefault("proxy", self.proxy_url)
