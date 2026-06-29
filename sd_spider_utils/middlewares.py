from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from scrapy import signals
from scrapy.exceptions import (
    DownloadFailedError,
    DownloadTimeoutError,
    NotConfigured,
    NotSupported,
)
from scrapy.http import Headers, Request, Response
from scrapy.responsetypes import responsetypes
from scrapy.utils.misc import load_object
from twisted.internet.defer import Deferred, DeferredList
from twisted.internet.threads import deferToThreadPool
from twisted.python.threadpool import ThreadPool

logger = logging.getLogger(__name__)

BACKEND_META_KEY = "download_backend"
BACKEND_FALLBACKS_META_KEY = "backend_fallbacks"
_ACTIVE_BACKEND_META_KEY = "_sd_download_backend"
_FALLBACK_INDEX_META_KEY = "_sd_backend_fallback_index"

_BACKEND_ALIASES = {
    "default": "scrapy",
    "dp": "drission",
    "drissionpage": "drission",
    "drission_page": "drission",
    "dp_listen": "drission_listen",
    "drission_api": "drission_listen",
    "go_requests": "requests_go",
    "requestsgo": "requests_go",
}
_SUPPORTED_BACKENDS = {
    "scrapy",
    "requests_go",
    "drission",
    "drission_listen",
    "scrapling",
}
_BROWSER_BACKENDS = {"drission", "drission_listen", "scrapling"}
_REQUEST_HEADERS_TO_DROP = {
    "connection",
    "content-length",
    "host",
    "proxy-connection",
    "transfer-encoding",
}
_RESPONSE_HEADERS_TO_DROP = {
    "content-encoding",
    "content-length",
    "transfer-encoding",
}
_DEFAULT_BROWSER_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _normalize_backend(value: Any) -> str | None:
    if value is None:
        return None

    backend = str(value).strip().lower().replace("-", "_")
    backend = _BACKEND_ALIASES.get(backend, backend)
    if backend not in _SUPPORTED_BACKENDS:
        supported = ", ".join(sorted(_SUPPORTED_BACKENDS))
        raise ValueError(f"未知下载后端 {value!r}，可选值：{supported}")
    return backend


def _fallback_backends(request: Request) -> list[str]:
    values = request.meta.get(BACKEND_FALLBACKS_META_KEY) or []
    if isinstance(values, str):
        values = [value.strip() for value in values.split(",") if value.strip()]

    result = []
    for value in values:
        backend = _normalize_backend(value)
        if backend and (not result or result[-1] != backend):
            result.append(backend)
    return result


def _backend_for_request(request: Request) -> str | None:
    explicit_backend = _normalize_backend(request.meta.get(BACKEND_META_KEY))
    if explicit_backend:
        return explicit_backend

    fallbacks = _fallback_backends(request)
    if fallbacks:
        index = int(request.meta.get(_FALLBACK_INDEX_META_KEY, 0))
        if 0 <= index < len(fallbacks):
            return fallbacks[index]

    if request.meta.get("use_dp"):
        if request.meta.get("listen_path"):
            return "drission_listen"
        return "drission"
    if request.meta.get("use_scrapling"):
        return "scrapling"
    if request.meta.get("use_requests_go") or request.meta.get("use_go_requests"):
        return "requests_go"
    return None


def _mask_proxy_url(proxy_url: str) -> str:
    """脱敏代理地址，避免日志泄露账户密码。"""
    if not proxy_url:
        return proxy_url

    has_scheme = "://" in proxy_url
    value = proxy_url if has_scheme else f"//{proxy_url}"
    try:
        parts = urlsplit(value)
        hostname = parts.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        port = ":" + str(parts.port) if parts.port else ""
        netloc = f"{hostname}{port}"
        if has_scheme:
            return urlunsplit(
                (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
            )
        suffix = parts.path
        if parts.query:
            suffix += f"?{parts.query}"
        if parts.fragment:
            suffix += f"#{parts.fragment}"
        return f"{netloc}{suffix}"
    except (TypeError, ValueError):
        return "<invalid-proxy-url>"


def _request_timeout(request: Request, default: float) -> float:
    timeout = request.meta.get("download_timeout", default)
    try:
        timeout = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"download_timeout 必须是数字，当前值：{timeout!r}") from exc
    if timeout <= 0:
        raise ValueError("download_timeout 必须大于 0")
    return timeout


def _request_headers(request: Request, *, for_browser: bool = False) -> dict[str, str]:
    headers = dict(request.headers.to_unicode_dict())
    if not headers:
        headers.update(_DEFAULT_BROWSER_HEADERS)

    for name in tuple(headers):
        if name.lower() in _REQUEST_HEADERS_TO_DROP:
            headers.pop(name, None)

    if for_browser:
        for name in tuple(headers):
            if name.lower() in {"cookie", "user-agent"}:
                headers.pop(name, None)
    return headers


def _request_cookies(request: Request) -> list[dict[str, str]]:
    raw_cookie = request.headers.get("Cookie")
    if not raw_cookie:
        return []

    cookie_header = raw_cookie.decode("latin-1")
    cookies = []
    for item in cookie_header.split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name:
            cookies.append({"name": name, "value": value, "url": request.url})
    return cookies


def _body_to_bytes(body: Any, headers: Headers) -> bytes:
    if body is None:
        return b""
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    if isinstance(body, (dict, list)):
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json; charset=utf-8"
        return json.dumps(body, ensure_ascii=False).encode("utf-8")
    return str(body).encode("utf-8")


def _headers_with_cookies(headers: Any, cookies: Any) -> Headers:
    response_headers = Headers(headers or {})
    if not cookies:
        return response_headers

    if isinstance(cookies, dict):
        if "name" in cookies:
            cookie_values = [cookies]
        else:
            cookie_values = [
                {"name": name, "value": value} for name, value in cookies.items()
            ]
    else:
        cookie_values = list(cookies)

    existing_cookie_names = {
        value.decode("latin-1").split("=", 1)[0].strip().lower()
        for value in response_headers.getlist("Set-Cookie")
        if b"=" in value
    }
    for cookie in cookie_values:
        if not isinstance(cookie, dict):
            continue
        name = cookie.get("name") or cookie.get("Name")
        value = cookie.get("value")
        if value is None:
            value = cookie.get("Value")
        if not name or name.lower() in existing_cookie_names:
            continue

        parts = [f"{name}={value or ''}"]
        domain = cookie.get("domain") or cookie.get("Domain")
        path = cookie.get("path") or cookie.get("Path")
        same_site = cookie.get("sameSite") or cookie.get("SameSite")
        if domain:
            parts.append(f"Domain={domain}")
        if path:
            parts.append(f"Path={path}")
        if cookie.get("secure") or cookie.get("Secure"):
            parts.append("Secure")
        if cookie.get("httpOnly") or cookie.get("HttpOnly"):
            parts.append("HttpOnly")
        if same_site:
            parts.append(f"SameSite={same_site}")
        response_headers.appendlist("Set-Cookie", "; ".join(parts))
        existing_cookie_names.add(name.lower())
    return response_headers


def _scrapy_response(
    request: Request,
    *,
    backend: str,
    url: str | None,
    status: int | None,
    headers: Any,
    body: Any,
) -> Response:
    response_headers = Headers(headers or {})
    for name in _RESPONSE_HEADERS_TO_DROP:
        response_headers.pop(name, None)

    response_body = _body_to_bytes(body, response_headers)
    response_url = url or request.url
    try:
        response_status = int(status or 0)
    except (TypeError, ValueError) as exc:
        raise DownloadFailedError(f"{backend} 返回了无效状态码：{status!r}") from exc
    if not 100 <= response_status <= 599:
        raise DownloadFailedError(f"{backend} 返回了无效状态码：{response_status!r}")

    response_class = responsetypes.from_args(
        headers=response_headers,
        url=response_url,
        body=response_body,
    )
    return response_class(
        url=response_url,
        status=response_status,
        headers=response_headers,
        body=response_body,
        request=request,
        flags=[f"download-backend:{backend}"],
    )


def _is_timeout_exception(exception: Exception) -> bool:
    name = exception.__class__.__name__.lower()
    message = str(exception).lower()
    return "timeout" in name or "timed out" in message or "超时" in message


def _normalize_backend_exception(backend: str, exception: Exception) -> Exception:
    if isinstance(
        exception,
        (DownloadFailedError, DownloadTimeoutError, NotSupported),
    ):
        return exception
    if isinstance(exception, (ImportError, ModuleNotFoundError)):
        return exception
    if _is_timeout_exception(exception):
        return DownloadTimeoutError(f"{backend} 下载超时：{exception}")
    return DownloadFailedError(f"{backend} 下载失败：{exception}")


def _close_quietly(resource: Any, method_name: str) -> None:
    if resource is None:
        return
    try:
        getattr(resource, method_name)()
    except Exception:
        logger.debug("关闭资源失败", exc_info=True)


@dataclass
class _BrowserEntry:
    browser: Any
    active: int = 0
    last_used: float = 0.0


@dataclass
class _ScraplingSessionEntry:
    session: Any
    last_used: float = 0.0


class _DrissionBrowserPool:
    """每个 crawler 独享的、按代理和 cookiejar 隔离的浏览器池。"""

    def __init__(
        self,
        *,
        max_browsers: int,
        headless: bool,
        load_mode: str | None,
    ) -> None:
        self.max_browsers = max(1, max_browsers)
        self.headless = headless
        self.load_mode = load_mode
        self._entries: dict[tuple[str, str], _BrowserEntry] = {}
        self._condition = threading.Condition()

    def _create_browser(self, proxy: str | None) -> Any:
        from DrissionPage import Chromium, ChromiumOptions

        options = ChromiumOptions().auto_port().headless(self.headless)
        if self.load_mode:
            options.set_load_mode(self.load_mode)
        if proxy:
            options.set_proxy(proxy)
        return Chromium(options)

    def acquire(
        self,
        *,
        proxy: str | None,
        cookiejar: Any,
        timeout: float,
    ) -> tuple[tuple[str, str], _BrowserEntry]:
        key = (proxy or "", str(cookiejar if cookiejar is not None else "default"))
        deadline = monotonic() + timeout
        evicted_browser = None

        with self._condition:
            while key not in self._entries and len(self._entries) >= self.max_browsers:
                idle_entries = [
                    (candidate_key, entry)
                    for candidate_key, entry in self._entries.items()
                    if entry.active == 0
                ]
                if idle_entries:
                    evicted_key, evicted_entry = min(
                        idle_entries,
                        key=lambda item: item[1].last_used,
                    )
                    self._entries.pop(evicted_key)
                    evicted_browser = evicted_entry.browser
                    break

                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise DownloadTimeoutError("等待可用 DrissionPage 浏览器实例超时")
                self._condition.wait(remaining)

            if evicted_browser is not None:
                _close_quietly(evicted_browser, "quit")

            entry = self._entries.get(key)
            if entry is None:
                entry = _BrowserEntry(browser=self._create_browser(proxy))
                self._entries[key] = entry
            entry.active += 1
            entry.last_used = monotonic()
            return key, entry

    def release(self, key: tuple[str, str], entry: _BrowserEntry) -> None:
        with self._condition:
            current = self._entries.get(key)
            if current is entry:
                current.active = max(0, current.active - 1)
                current.last_used = monotonic()
            self._condition.notify_all()

    def invalidate(self, key: tuple[str, str], entry: _BrowserEntry) -> None:
        with self._condition:
            if self._entries.get(key) is entry:
                self._entries.pop(key)
            self._condition.notify_all()
        _close_quietly(entry.browser, "quit")

    def close(self) -> None:
        with self._condition:
            entries = list(self._entries.values())
            self._entries.clear()
            self._condition.notify_all()
        for entry in entries:
            _close_quietly(entry.browser, "quit")


class BackendRouterMiddleware:
    """按 Request.meta 显式选择下载后端，并统一适配 Scrapy 请求和响应。"""

    accepted_backends: frozenset[str] | None = None

    def __init__(self, crawler: Any) -> None:
        self.crawler = crawler
        self.settings = crawler.settings
        self.default_timeout = self.settings.getfloat("DOWNLOAD_TIMEOUT", 30.0)
        self.max_threads = max(
            1,
            self.settings.getint("SD_DOWNLOADER_MAX_THREADS", 4),
        )
        self._thread_pool: ThreadPool | None = None
        self._scrapling_thread_pool: ThreadPool | None = None
        self._pool_lock = threading.Lock()
        self._drission_pool: _DrissionBrowserPool | None = None
        self._scrapling_sessions: dict[tuple[str, str], _ScraplingSessionEntry] = {}

        fallback_codes = self.settings.getlist(
            "SD_BACKEND_FALLBACK_HTTP_CODES",
            [403, 429, 503],
        )
        self.fallback_http_codes = {int(code) for code in fallback_codes}
        self.challenge_markers = tuple(
            marker.lower().encode("utf-8")
            for marker in self.settings.getlist(
                "SD_BACKEND_CHALLENGE_MARKERS",
                [
                    "<title>just a moment",
                    "/cdn-cgi/challenge-platform/",
                    "cf-chl-",
                ],
            )
        )

    @classmethod
    def from_crawler(cls, crawler: Any) -> "BackendRouterMiddleware":
        middleware = cls(crawler)
        crawler.signals.connect(
            middleware.spider_closed,
            signal=signals.spider_closed,
        )
        return middleware

    def _get_thread_pool(self, backend: str) -> ThreadPool:
        with self._pool_lock:
            if backend == "scrapling":
                if self._scrapling_thread_pool is None:
                    self._scrapling_thread_pool = ThreadPool(
                        minthreads=1,
                        maxthreads=1,
                        name="sd-scrapling",
                    )
                    self._scrapling_thread_pool.start()
                return self._scrapling_thread_pool

            if self._thread_pool is None:
                self._thread_pool = ThreadPool(
                    minthreads=0,
                    maxthreads=self.max_threads,
                    name="sd-downloaders",
                )
                self._thread_pool.start()
            return self._thread_pool

    def _accepts(self, backend: str | None) -> bool:
        if not backend:
            return False
        return self.accepted_backends is None or backend in self.accepted_backends

    def process_request(self, request: Request) -> Deferred | None:
        backend = _backend_for_request(request)
        if not self._accepts(backend):
            return None

        request.meta[_ACTIVE_BACKEND_META_KEY] = backend
        if backend == "scrapy":
            return None
        if backend in _BROWSER_BACKENDS and request.method != "GET":
            raise NotSupported(
                f"{backend} 后端只支持 GET，收到 {request.method} {request.url}"
            )

        timeout = _request_timeout(request, self.default_timeout)
        started_at = monotonic()
        thread_pool = self._get_thread_pool(backend)

        # 中间件模块不能在导入阶段安装 reactor；此时 Scrapy 已完成 reactor 初始化。
        from twisted.internet import reactor

        deferred = deferToThreadPool(
            reactor,
            thread_pool,
            self._download,
            backend,
            request,
            timeout,
        )
        deferred.addCallback(
            self._record_success,
            backend,
            started_at,
        )
        deferred.addErrback(
            self._record_failure,
            backend,
            started_at,
        )
        return deferred

    def process_response(
        self,
        request: Request,
        response: Response,
    ) -> Request | Response:
        fallbacks = _fallback_backends(request)
        if not fallbacks:
            return response

        current_index = int(request.meta.get(_FALLBACK_INDEX_META_KEY, 0))
        if current_index + 1 >= len(fallbacks):
            return response

        body_prefix = response.body[:65536].lower()
        has_challenge = any(marker in body_prefix for marker in self.challenge_markers)
        if response.status not in self.fallback_http_codes and not has_challenge:
            return response

        next_index = current_index + 1
        next_backend = fallbacks[next_index]
        new_meta = request.meta.copy()
        new_meta[_FALLBACK_INDEX_META_KEY] = next_index
        new_meta[BACKEND_META_KEY] = next_backend
        new_meta.pop(_ACTIVE_BACKEND_META_KEY, None)
        self.crawler.stats.inc_value(
            f"sd_downloader/fallback/{fallbacks[current_index]}_to_{next_backend}"
        )
        logger.warning(
            "下载后端降级：%s -> %s，状态码=%s，URL=%s",
            fallbacks[current_index],
            next_backend,
            response.status,
            request.url,
            extra={"spider": self.crawler.spider},
        )
        return request.replace(meta=new_meta, dont_filter=True)

    def _record_success(
        self,
        response: Response,
        backend: str,
        started_at: float,
    ) -> Response:
        self.crawler.stats.inc_value(f"sd_downloader/{backend}/response_count")
        self.crawler.stats.inc_value(
            f"sd_downloader/{backend}/response_status_count/{response.status}"
        )
        self.crawler.stats.set_value(
            f"sd_downloader/{backend}/last_latency_seconds",
            monotonic() - started_at,
        )
        return response

    def _record_failure(
        self,
        failure: Any,
        backend: str,
        started_at: float,
    ) -> Any:
        self.crawler.stats.inc_value(f"sd_downloader/{backend}/exception_count")
        self.crawler.stats.set_value(
            f"sd_downloader/{backend}/last_latency_seconds",
            monotonic() - started_at,
        )
        return failure

    def _download(
        self,
        backend: str,
        request: Request,
        timeout: float,
    ) -> Response:
        try:
            if backend == "requests_go":
                return self._download_requests_go(request, timeout)
            if backend == "drission":
                return self._download_drission(request, timeout)
            if backend == "drission_listen":
                return self._download_drission_listen(request, timeout)
            if backend == "scrapling":
                return self._download_scrapling(request, timeout)
            raise NotSupported(f"不支持的下载后端：{backend}")
        except Exception as exc:
            normalized = _normalize_backend_exception(backend, exc)
            if normalized is exc:
                raise
            raise normalized from exc

    def _download_requests_go(
        self,
        request: Request,
        timeout: float,
    ) -> Response:
        import requests_go

        proxy = request.meta.get("proxy")
        proxies = {"http": proxy, "https": proxy} if proxy else None
        kwargs = {
            "method": request.method,
            "url": request.url,
            "headers": _request_headers(request),
            "timeout": timeout,
            "allow_redirects": False,
            "proxies": proxies,
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
            backend="requests_go",
            url=response.url,
            status=response.status_code,
            headers=response.headers,
            body=response.content,
        )

    def _get_drission_pool(self) -> _DrissionBrowserPool:
        if self._drission_pool is None:
            self._drission_pool = _DrissionBrowserPool(
                max_browsers=self.settings.getint(
                    "SD_DRISSION_MAX_BROWSERS",
                    self.max_threads,
                ),
                headless=self.settings.getbool("SD_DRISSION_HEADLESS", True),
                load_mode=self.settings.get("SD_DRISSION_LOAD_MODE"),
            )
        return self._drission_pool

    @staticmethod
    def _prepare_drission_tab(tab: Any, request: Request) -> None:
        user_agent = request.headers.get("User-Agent")
        if user_agent:
            tab.set.user_agent(user_agent.decode("latin-1"))

        headers = _request_headers(request, for_browser=True)
        if headers:
            tab.set.headers(headers)

        cookies = _request_cookies(request)
        if cookies:
            tab.set.cookies(cookies)

    @staticmethod
    def _drain_document_packets(tab: Any, timeout: float) -> list[Any]:
        packets = []
        first_timeout = min(0.5, max(0.05, timeout))
        packet = tab.listen.wait(
            timeout=first_timeout,
            fit_count=True,
            raise_err=False,
        )
        if packet:
            packets.append(packet)
        while packet:
            packet = tab.listen.wait(
                timeout=0.05,
                fit_count=True,
                raise_err=False,
            )
            if packet:
                packets.append(packet)
        return packets

    @staticmethod
    def _select_document_packet(packets: list[Any], final_url: str) -> Any:
        normalized_url = final_url.rstrip("/")
        for packet in reversed(packets):
            if str(packet.url).rstrip("/") == normalized_url:
                return packet
        return packets[-1] if packets else None

    def _with_drission_tab(
        self,
        request: Request,
        timeout: float,
        callback: Any,
    ) -> Response:
        pool = self._get_drission_pool()
        proxy = request.meta.get("proxy")
        cookiejar = request.meta.get("cookiejar")
        key, entry = pool.acquire(
            proxy=proxy,
            cookiejar=cookiejar,
            timeout=timeout,
        )
        tab = None
        try:
            try:
                tab = entry.browser.new_tab()
            except Exception:
                pool.invalidate(key, entry)
                key, entry = pool.acquire(
                    proxy=proxy,
                    cookiejar=cookiejar,
                    timeout=timeout,
                )
                tab = entry.browser.new_tab()
            self._prepare_drission_tab(tab, request)
            return callback(tab)
        finally:
            _close_quietly(tab, "close")
            pool.release(key, entry)

    def _download_drission(
        self,
        request: Request,
        timeout: float,
    ) -> Response:
        def download(tab: Any) -> Response:
            started_at = monotonic()
            tab.listen.start(targets=True, method="GET", res_type="Document")
            result = tab.get(request.url, timeout=timeout)
            remaining = max(0.05, timeout - (monotonic() - started_at))
            packets = self._drain_document_packets(tab, remaining)
            packet = self._select_document_packet(packets, tab.url)
            if not result or packet is None or not packet.response:
                raise DownloadFailedError(
                    f"DrissionPage 未取得主文档响应：{request.url}"
                )
            packet.wait_extra_info(timeout=min(0.2, remaining))
            return _scrapy_response(
                request,
                backend="drission",
                url=tab.url or packet.url,
                status=packet.response.status,
                headers=_headers_with_cookies(
                    packet.response.headers,
                    tab.cookies(all_domains=False, all_info=True),
                ),
                body=tab.html,
            )

        return self._with_drission_tab(request, timeout, download)

    def _download_drission_listen(
        self,
        request: Request,
        timeout: float,
    ) -> Response:
        listen_path = request.meta.get("listen_path")
        if not listen_path:
            raise ValueError("drission_listen 后端必须设置 request.meta['listen_path']")

        def download(tab: Any) -> Response:
            started_at = monotonic()
            tab.listen.start(listen_path)
            result = tab.get(request.url, timeout=timeout)
            if not result:
                raise DownloadFailedError(f"DrissionPage 页面加载失败：{request.url}")
            remaining = timeout - (monotonic() - started_at)
            if remaining <= 0:
                raise DownloadTimeoutError(
                    f"等待接口 {listen_path!r} 超时：{request.url}"
                )
            packet = tab.listen.wait(
                timeout=remaining,
                fit_count=True,
                raise_err=False,
            )
            if not packet or not packet.response:
                raise DownloadTimeoutError(
                    f"等待接口 {listen_path!r} 超时：{request.url}"
                )
            packet.wait_extra_info(timeout=min(0.2, remaining))
            body = packet.response.raw_body
            if body is None:
                body = packet.response.body
            return _scrapy_response(
                request,
                backend="drission_listen",
                url=packet.url,
                status=packet.response.status,
                headers=_headers_with_cookies(
                    packet.response.headers,
                    tab.cookies(all_domains=False, all_info=True),
                ),
                body=body,
            )

        return self._with_drission_tab(request, timeout, download)

    def _get_scrapling_session(self, request: Request) -> Any:
        proxy = request.meta.get("proxy")
        cookiejar = request.meta.get("cookiejar")
        key = (proxy or "", str(cookiejar if cookiejar is not None else "default"))
        entry = self._scrapling_sessions.get(key)
        if entry is not None:
            entry.last_used = monotonic()
            return entry.session

        max_sessions = max(
            1,
            self.settings.getint("SD_SCRAPLING_MAX_SESSIONS", 4),
        )
        if len(self._scrapling_sessions) >= max_sessions:
            evicted_key, evicted_entry = min(
                self._scrapling_sessions.items(),
                key=lambda item: item[1].last_used,
            )
            self._scrapling_sessions.pop(evicted_key)
            _close_quietly(evicted_entry.session, "close")

        from scrapling.fetchers import StealthySession

        options = dict(self.settings.getdict("SD_SCRAPLING_SESSION_OPTIONS"))
        options.setdefault(
            "headless",
            self.settings.getbool("SD_SCRAPLING_HEADLESS", True),
        )
        options.setdefault("solve_cloudflare", False)
        options.setdefault("retries", 1)
        if proxy:
            options["proxy"] = proxy
        session = StealthySession(**options)
        session.start()
        self._scrapling_sessions[key] = _ScraplingSessionEntry(
            session=session,
            last_used=monotonic(),
        )
        return session

    def _download_scrapling(
        self,
        request: Request,
        timeout: float,
    ) -> Response:
        options = dict(request.meta.get("scrapling_options") or {})
        options["timeout"] = timeout * 1000
        options.pop("proxy", None)
        options.setdefault(
            "solve_cloudflare",
            bool(request.meta.get("solve_cloudflare", False)),
        )

        headers = _request_headers(request)
        if headers:
            options["extra_headers"] = {
                **headers,
                **dict(options.get("extra_headers") or {}),
            }
        if request.headers.get("Referer"):
            options.setdefault("google_search", False)

        cookies = _request_cookies(request)
        user_page_setup = options.get("page_setup")
        if cookies or user_page_setup:

            def page_setup(page: Any) -> None:
                if cookies:
                    page.context.add_cookies(cookies)
                if user_page_setup:
                    user_page_setup(page)

            options["page_setup"] = page_setup

        page = self._get_scrapling_session(request).fetch(request.url, **options)
        return _scrapy_response(
            request,
            backend="scrapling",
            url=page.url,
            status=page.status,
            headers=_headers_with_cookies(page.headers, page.cookies),
            body=page.body,
        )

    def _close_scrapling_sessions(self) -> None:
        entries = list(self._scrapling_sessions.values())
        self._scrapling_sessions.clear()
        for entry in entries:
            _close_quietly(entry.session, "close")

    def spider_closed(self, spider: Any, reason: str) -> Deferred | None:
        deferreds = []

        # Scrapling 的同步 Session 必须在创建它的同一工作线程中关闭。
        if self._scrapling_sessions and self._scrapling_thread_pool:
            from twisted.internet import reactor

            deferreds.append(
                deferToThreadPool(
                    reactor,
                    self._scrapling_thread_pool,
                    self._close_scrapling_sessions,
                )
            )

        if self._drission_pool is not None and self._thread_pool:
            drission_pool = self._drission_pool
            self._drission_pool = None
            from twisted.internet import reactor

            deferreds.append(
                deferToThreadPool(
                    reactor,
                    self._thread_pool,
                    drission_pool.close,
                )
            )

        if not deferreds:
            self._stop_thread_pools()
            return None

        result = DeferredList(deferreds, consumeErrors=True)
        result.addBoth(self._stop_thread_pools)
        return result

    def _stop_thread_pools(self, result: Any = None) -> Any:
        for attribute in ("_scrapling_thread_pool", "_thread_pool"):
            thread_pool = getattr(self, attribute)
            setattr(self, attribute, None)
            if thread_pool is not None:
                thread_pool.stop()
        return result


class DrissionPageMiddleware(BackendRouterMiddleware):
    """兼容旧配置：仅处理 download_backend='drission' 或 use_dp=True。"""

    accepted_backends = frozenset({"drission"})


class DrissionPageListenAPIMiddleware(BackendRouterMiddleware):
    """兼容旧配置：仅处理 DrissionPage 接口监听请求。"""

    accepted_backends = frozenset({"drission_listen"})


class RequestsGoMMiddleware(BackendRouterMiddleware):
    """仅处理显式选择 requests_go 的请求，不再拦截全部请求。"""

    accepted_backends = frozenset({"requests_go"})


class ScraplingMiddleware(BackendRouterMiddleware):
    """仅处理显式选择 Scrapling 的请求。"""

    accepted_backends = frozenset({"scrapling"})


class ProxyPoolMiddleware:
    """从静态配置或代理提供器为请求分配代理，并回报使用结果。"""

    def __init__(
        self,
        proxy_url: str | None,
        provider: Any = None,
        crawler: Any = None,
    ) -> None:
        self.proxy_url = proxy_url
        self.provider = provider
        self.crawler = crawler

    @classmethod
    def from_crawler(cls, crawler: Any) -> "ProxyPoolMiddleware":
        proxy_url = crawler.settings.get("SD_PROXY_URL")
        provider = crawler.settings.get("SD_PROXY_PROVIDER")
        if provider:
            provider = load_object(provider) if isinstance(provider, str) else provider
            if hasattr(provider, "from_crawler"):
                provider = provider.from_crawler(crawler)
            elif isinstance(provider, type):
                provider = provider()
        if not proxy_url and provider is None:
            raise NotConfigured(
                "请设置 SD_PROXY_URL 或 SD_PROXY_PROVIDER；"
                "已有 request.meta['proxy'] 时无需启用此中间件"
            )
        return cls(proxy_url=proxy_url, provider=provider, crawler=crawler)

    @property
    def spider(self) -> Any:
        return self.crawler.spider if self.crawler is not None else None

    def _get_proxy(self, request: Request) -> str | None:
        if self.provider is None:
            return self.proxy_url
        if hasattr(self.provider, "get_proxy"):
            return self.provider.get_proxy(request=request, spider=self.spider)
        return self.provider(request=request, spider=self.spider)

    def process_request(self, request: Request) -> None:
        if request.meta.get("proxy"):
            return
        proxy = self._get_proxy(request)
        if proxy:
            request.meta["proxy"] = proxy
            request.meta["_sd_assigned_proxy"] = proxy
            logger.debug(
                "为请求分配代理 %s：%s",
                _mask_proxy_url(proxy),
                request.url,
                extra={"spider": self.spider},
            )

    def process_response(
        self,
        request: Request,
        response: Response,
    ) -> Response:
        proxy = request.meta.get("_sd_assigned_proxy")
        reporter = getattr(self.provider, "report_response", None)
        if proxy and reporter:
            reporter(
                proxy=proxy,
                response=response,
                request=request,
                spider=self.spider,
            )
        return response

    def process_exception(
        self,
        request: Request,
        exception: Exception,
    ) -> None:
        proxy = request.meta.get("_sd_assigned_proxy")
        reporter = getattr(self.provider, "report_exception", None)
        if proxy and reporter:
            reporter(
                proxy=proxy,
                exception=exception,
                request=request,
                spider=self.spider,
            )


class TunnelProxyMiddleware(ProxyPoolMiddleware):
    """向后兼容名称；新项目建议使用 ProxyPoolMiddleware。"""
