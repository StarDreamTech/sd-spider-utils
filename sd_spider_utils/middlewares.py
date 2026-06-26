from urllib.parse import urlsplit, urlunsplit

from scrapy.http import HtmlResponse
from twisted.internet.threads import deferToThread

from sd_spider_utils.dp_utils import SingletonChromium


def _mask_proxy_url(proxy_url: str) -> str:
    """脱敏代理地址，避免日志泄露账户密码。"""
    if not proxy_url:
        return proxy_url

    parts = urlsplit(proxy_url)
    hostname = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{hostname}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _build_chromium_options(proxy=None):
    from DrissionPage import ChromiumOptions

    co = ChromiumOptions()
    if proxy:
        co.set_proxy(proxy)
    return co


def _new_chromium_tab(proxy=None):
    if getattr(SingletonChromium, "_proxy", None) != proxy:
        SingletonChromium.reset_instance()
        SingletonChromium._proxy = proxy

    co = _build_chromium_options(proxy)
    chrome = SingletonChromium.get_instance(co)
    try:
        return chrome, chrome.new_tab()
    except Exception:
        # 浏览器被手动关闭或连接断开时，重建单例后再开新标签页。
        SingletonChromium.reset_instance()
        chrome = SingletonChromium.get_instance(co)
        return chrome, chrome.new_tab()


def _close_tab(tab):
    if not tab:
        return
    try:
        tab.close()
    except Exception:
        pass


def _html_response(request, body, status=200):
    if not isinstance(body, bytes):
        body = str(body).encode("utf-8")

    return HtmlResponse(
        request.url,
        status=status,
        body=body,
        encoding="utf-8",
        request=request,
    )


class DrissionPageMiddleware:
    """使用 DrissionPage 渲染普通页面，返回浏览器执行后的 HTML。"""

    def process_request(self, request, spider):
        meta = request.meta
        use_dp = meta.get("use_dp")
        listen_path = meta.get("listen_path")
        proxy = meta.get("proxy")
        timeout = meta.get("timeout", 30)

        if not use_dp or listen_path:
            return None
        print("use dp middleware")

        return deferToThread(self._process_request, request, proxy, timeout)

    def _process_request(self, request, proxy, timeout):
        new_tab = None
        try:
            _, new_tab = _new_chromium_tab(proxy)
            new_tab.get(request.url, timeout=timeout)
            return _html_response(request, new_tab.html)
        finally:
            _close_tab(new_tab)


class DrissionPageListenAPIMiddleware:
    """使用 DrissionPage 监听接口，优先返回匹配接口的数据包内容。"""

    def process_request(self, request, spider):
        meta = request.meta
        use_dp = meta.get("use_dp")
        listen_path = meta.get("listen_path")
        proxy = meta.get("proxy")
        timeout = meta.get("timeout", 30)
        download_timeout = meta.get("download_timeout", 30)

        if not use_dp or not listen_path:
            return None

        print("use dp listen_api middleware")

        return deferToThread(
            self._process_request,
            request,
            proxy,
            timeout,
            listen_path,
            download_timeout,
        )

    def _process_request(self, request, proxy, timeout, listen_path, download_timeout):
        import json

        new_tab = None
        try:
            _, new_tab = _new_chromium_tab(proxy)
            new_tab.listen.start(listen_path)  # 指定要匹配的接口路径或关键文本。
            new_tab.get(request.url, timeout=timeout)

            res = new_tab.listen.wait(timeout=download_timeout)
            if res and not isinstance(res, bool) and res.response:
                body = res.response.body
                status = res.response.status
                if isinstance(body, (dict, list)):
                    body = json.dumps(body, ensure_ascii=False)
                return _html_response(request, body, status=status)

            # 监听超时或没有匹配包时，回退到页面 HTML，方便 spider 继续解析。
            return _html_response(request, new_tab.html)
        finally:
            _close_tab(new_tab)


class RequestsGoMMiddleware:
    def __init__(self) -> None:
        super().__init__()

    def process_request(self, request, spider):
        return deferToThread(self._process_request, request, spider)

    def _process_request(self, request, spider):
        import requests_go as requests

        print("use go_requests middleware")

        proxies = None
        if request.meta.get("proxy"):
            proxy = request.meta.get("proxy")
            if proxy:
                proxies = {
                    "http": proxy,
                    "https": proxy,
                }
                print(f"RequestsGoMMiddleware 使用代理: {_mask_proxy_url(proxy)}")

        common_kwargs = {
            "url": request.url,
            "headers": {
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
                "cache-control": "max-age=0",
                "priority": "u=0, i",
                "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "none",
                "sec-fetch-user": "?1",
                "upgrade-insecure-requests": "1",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
            },
            "timeout": 60,
            "tls_config": requests.tls_config.TLS_CHROME_LATEST,
            "proxies": proxies,
        }
        if request.meta.get("headers"):
            common_kwargs["headers"] = request.meta["headers"]
        if request.meta.get("cookies"):
            common_kwargs["cookies"] = request.meta["cookies"]

        if request.method == "POST":
            response = requests.post(**common_kwargs, data=request.body)
        else:
            response = requests.get(**common_kwargs)

        resp = HtmlResponse(
            request.url,
            status=response.status_code,
            body=response.content,
            encoding="utf-8",
            request=request,
        )
        return resp


class TunnelProxyMiddleware:
    def process_request(self, request, spider):
        if proxy:=request.meta.get("proxy"):
            request.meta["proxy"] = proxy
            print(f"使用了代理{_mask_proxy_url(proxy)}")


class ScraplingMiddleware:
    def __init__(self) -> None:
        super().__init__()

    def process_request(self, request, spider):
        if not request.meta.get("use_scrapling"):
            return None

        def fetch_in_clean_thread():
            import asyncio
            try:
                asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            from scrapling import StealthyFetcher
            proxy = request.meta.get("proxy")
            return StealthyFetcher.fetch(request.url, solve_cloudflare=True, proxy=proxy)

        return deferToThread(fetch_in_clean_thread).addCallback(
            lambda page: HtmlResponse(
                page.url,
                status=page.status,
                body=page.html_content,
                encoding="utf-8",
                request=request,
            )
        )
