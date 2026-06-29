import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scrapy.exceptions import DownloadFailedError, DownloadTimeoutError, NotSupported
from scrapy.http import HtmlResponse, Request
from scrapy.settings import Settings

from sd_spider_utils.middlewares import (
    BACKEND_FALLBACKS_META_KEY,
    BACKEND_META_KEY,
    BackendRouterMiddleware,
    ProxyPoolMiddleware,
    RequestsGoMMiddleware,
    _DrissionBrowserPool,
    _backend_for_request,
    _headers_with_cookies,
    _mask_proxy_url,
    _normalize_backend_exception,
    _request_headers,
    _scrapy_response,
)


class DummyStats:
    def __init__(self):
        self.values = {}

    def inc_value(self, key, count=1, start=0):
        self.values[key] = self.values.get(key, start) + count

    def set_value(self, key, value):
        self.values[key] = value


class DummySignals:
    def connect(self, receiver, signal):
        return None


class DummyCrawler:
    def __init__(self, settings=None):
        self.settings = Settings(settings or {})
        self.stats = DummyStats()
        self.signals = DummySignals()
        self.spider = None


class BackendRoutingTests(unittest.TestCase):
    def test_optional_drission_module_is_not_imported_by_package(self):
        self.assertNotIn("sd_spider_utils.dp_utils", sys.modules)

    def test_backend_selection_is_explicit_and_supports_legacy_flags(self):
        self.assertIsNone(_backend_for_request(Request("https://example.com")))
        self.assertEqual(
            _backend_for_request(
                Request(
                    "https://example.com",
                    meta={BACKEND_META_KEY: "requests-go"},
                )
            ),
            "requests_go",
        )
        self.assertEqual(
            _backend_for_request(
                Request(
                    "https://example.com",
                    meta={"use_dp": True, "listen_path": "/api/data"},
                )
            ),
            "drission_listen",
        )
        self.assertEqual(
            _backend_for_request(
                Request("https://example.com", meta={"use_scrapling": True})
            ),
            "scrapling",
        )

    def test_requests_go_middleware_no_longer_intercepts_all_requests(self):
        middleware = RequestsGoMMiddleware(DummyCrawler())
        request = Request("https://example.com")
        self.assertIsNone(middleware.process_request(request))
        middleware._stop_thread_pools()

    def test_browser_backends_reject_non_get_requests(self):
        middleware = BackendRouterMiddleware(DummyCrawler())
        request = Request(
            "https://example.com",
            method="POST",
            body=b"x=1",
            meta={BACKEND_META_KEY: "scrapling"},
        )
        with self.assertRaises(NotSupported):
            middleware.process_request(request)
        middleware._stop_thread_pools()

    def test_fallback_moves_to_next_backend(self):
        middleware = BackendRouterMiddleware(DummyCrawler())
        request = Request(
            "https://example.com",
            meta={
                BACKEND_FALLBACKS_META_KEY: [
                    "scrapy",
                    "requests_go",
                    "scrapling",
                ]
            },
        )
        response = HtmlResponse(
            request.url,
            status=403,
            body=b"forbidden",
            request=request,
        )

        retry_request = middleware.process_response(request, response)

        self.assertIsInstance(retry_request, Request)
        self.assertTrue(retry_request.dont_filter)
        self.assertEqual(retry_request.meta[BACKEND_META_KEY], "requests_go")
        self.assertEqual(_backend_for_request(retry_request), "requests_go")

    def test_fallback_detects_known_challenge_pages(self):
        middleware = BackendRouterMiddleware(DummyCrawler())
        request = Request(
            "https://example.com",
            meta={
                BACKEND_FALLBACKS_META_KEY: ["scrapy", "drission"],
            },
        )
        response = HtmlResponse(
            request.url,
            status=200,
            body=b"<html><title>Just a moment...</title></html>",
            request=request,
        )

        retry_request = middleware.process_response(request, response)

        self.assertIsInstance(retry_request, Request)
        self.assertEqual(retry_request.meta[BACKEND_META_KEY], "drission")


class RequestResponseAdapterTests(unittest.TestCase):
    def test_request_headers_preserve_cookie_and_drop_transport_headers(self):
        request = Request(
            "https://example.com",
            headers={
                "Cookie": "sid=abc",
                "Content-Length": "3",
                "Connection": "keep-alive",
                "X-Test": "yes",
            },
        )

        headers = _request_headers(request)

        self.assertEqual(headers["Cookie"], "sid=abc")
        self.assertEqual(headers["X-Test"], "yes")
        self.assertNotIn("Content-Length", headers)
        self.assertNotIn("Connection", headers)

    def test_response_preserves_url_status_headers_and_encoding(self):
        request = Request("https://example.com/start")
        body = "<html><p>中文</p></html>".encode("gb18030")

        response = _scrapy_response(
            request,
            backend="requests_go",
            url="https://example.com/final",
            status=302,
            headers={
                "Content-Type": "text/html; charset=gb18030",
                "Content-Encoding": "gzip",
                "Location": "/next",
                "Set-Cookie": "sid=abc; Path=/",
            },
            body=body,
        )

        self.assertEqual(response.url, "https://example.com/final")
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers["Location"], b"/next")
        self.assertEqual(response.headers["Set-Cookie"], b"sid=abc; Path=/")
        self.assertNotIn("Content-Encoding", response.headers)
        self.assertIn(response.encoding, {"gb18030", "gbk"})
        self.assertIn("中文", response.text)

    def test_invalid_status_is_not_silently_changed_to_200(self):
        with self.assertRaises(DownloadFailedError):
            _scrapy_response(
                Request("https://example.com"),
                backend="drission",
                url=None,
                status=None,
                headers={},
                body=b"",
            )

    def test_browser_cookies_are_exposed_to_scrapy_cookie_middleware(self):
        headers = _headers_with_cookies(
            {"Set-Cookie": "server=one; Path=/"},
            [
                {
                    "name": "browser",
                    "value": "two",
                    "domain": ".example.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": True,
                },
                {"name": "server", "value": "duplicate"},
            ],
        )

        values = [value.decode("latin-1") for value in headers.getlist("Set-Cookie")]
        self.assertEqual(len(values), 2)
        self.assertIn("server=one; Path=/", values)
        self.assertIn(
            "browser=two; Domain=.example.com; Path=/; Secure; HttpOnly",
            values,
        )

    def test_third_party_errors_are_normalized_for_scrapy_retry(self):
        timeout = _normalize_backend_exception(
            "requests_go",
            RuntimeError("operation timed out"),
        )
        failure = _normalize_backend_exception(
            "scrapling",
            RuntimeError("browser disconnected"),
        )

        self.assertIsInstance(timeout, DownloadTimeoutError)
        self.assertIsInstance(failure, DownloadFailedError)


class RequestsGoTests(unittest.TestCase):
    def test_all_request_semantics_are_forwarded(self):
        calls = []

        def fake_request(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                url="https://example.com/final",
                status_code=307,
                headers={
                    "Content-Type": "text/plain; charset=utf-8",
                    "Location": "/again",
                    "Set-Cookie": "sid=next; Path=/",
                },
                content=b"redirect",
            )

        fake_module = SimpleNamespace(
            request=fake_request,
            tls_config=SimpleNamespace(TLS_CHROME_LATEST=object()),
        )
        middleware = BackendRouterMiddleware(
            DummyCrawler({"SD_REQUESTS_GO_VERIFY": True})
        )
        request = Request(
            "https://example.com/start",
            method="PUT",
            headers={
                "Cookie": "sid=abc",
                "Content-Type": "application/octet-stream",
                "Content-Length": "3",
            },
            body=b"abc",
            meta={"proxy": "http://user:pass@127.0.0.1:8080"},
        )

        with patch.dict(sys.modules, {"requests_go": fake_module}):
            response = middleware._download_requests_go(request, timeout=12.5)

        self.assertEqual(len(calls), 1)
        sent = calls[0]
        self.assertEqual(sent["method"], "PUT")
        self.assertEqual(sent["data"], b"abc")
        self.assertEqual(sent["timeout"], 12.5)
        self.assertFalse(sent["allow_redirects"])
        self.assertEqual(sent["headers"]["Cookie"], "sid=abc")
        self.assertNotIn("Content-Length", sent["headers"])
        self.assertEqual(
            sent["proxies"]["https"],
            "http://user:pass@127.0.0.1:8080",
        )
        self.assertEqual(response.url, "https://example.com/final")
        self.assertEqual(response.status, 307)
        self.assertEqual(response.headers["Location"], b"/again")


class BrowserResourceTests(unittest.TestCase):
    def test_drission_pool_isolated_by_proxy_and_evicts_only_idle_browser(self):
        browsers = []

        class FakeBrowser:
            def __init__(self, proxy):
                self.proxy = proxy
                self.closed = False

            def quit(self):
                self.closed = True

        pool = _DrissionBrowserPool(
            max_browsers=1,
            headless=True,
            load_mode=None,
        )

        def create_browser(proxy):
            browser = FakeBrowser(proxy)
            browsers.append(browser)
            return browser

        pool._create_browser = create_browser
        key_a, entry_a = pool.acquire(
            proxy="http://proxy-a:8080",
            cookiejar="a",
            timeout=0.1,
        )
        with self.assertRaises(DownloadTimeoutError):
            pool.acquire(
                proxy="http://proxy-b:8080",
                cookiejar="b",
                timeout=0.01,
            )
        pool.release(key_a, entry_a)
        key_b, entry_b = pool.acquire(
            proxy="http://proxy-b:8080",
            cookiejar="b",
            timeout=0.1,
        )

        self.assertTrue(browsers[0].closed)
        self.assertEqual(entry_b.browser.proxy, "http://proxy-b:8080")
        pool.release(key_b, entry_b)
        pool.close()
        self.assertTrue(browsers[1].closed)

    def test_drission_listen_timeout_is_not_returned_as_fake_html_200(self):
        class FakeSet:
            def user_agent(self, value):
                pass

            def headers(self, value):
                pass

            def __init__(self):
                self.cookies = lambda value: None

        class FakeListener:
            def start(self, value):
                pass

            def wait(self, **kwargs):
                return False

        class FakeTab:
            def __init__(self):
                self.set = FakeSet()
                self.listen = FakeListener()
                self.closed = False

            def get(self, url, timeout):
                return True

            def close(self):
                self.closed = True

        tab = FakeTab()
        entry = SimpleNamespace(browser=SimpleNamespace(new_tab=lambda: tab))

        class FakePool:
            def acquire(self, **kwargs):
                return ("proxy", "cookiejar"), entry

            def release(self, key, released_entry):
                self.released = (key, released_entry)

            def invalidate(self, key, invalidated_entry):
                raise AssertionError("browser should not be invalidated")

        pool = FakePool()
        middleware = BackendRouterMiddleware(DummyCrawler())
        middleware._get_drission_pool = lambda: pool
        request = Request(
            "https://example.com",
            meta={"listen_path": "/api/data"},
        )

        with self.assertRaises(DownloadTimeoutError):
            middleware._download_drission_listen(request, timeout=0.05)

        self.assertTrue(tab.closed)
        self.assertEqual(pool.released[1], entry)

    def test_scrapling_sessions_are_isolated_by_proxy_and_cookiejar(self):
        created = []

        class FakeStealthySession:
            def __init__(self, **options):
                self.options = options
                self.started = False
                self.closed = False
                created.append(self)

            def start(self):
                self.started = True

            def close(self):
                self.closed = True

        middleware = BackendRouterMiddleware(
            DummyCrawler({"SD_SCRAPLING_MAX_SESSIONS": 2})
        )
        request_a = Request(
            "https://example.com",
            meta={"cookiejar": "account-a", "proxy": "http://proxy-a:8080"},
        )
        request_a_again = request_a.copy()
        request_b = Request(
            "https://example.com",
            meta={"cookiejar": "account-b", "proxy": "http://proxy-a:8080"},
        )
        request_c = Request(
            "https://example.com",
            meta={"cookiejar": "account-c", "proxy": "http://proxy-b:8080"},
        )
        fake_fetchers = SimpleNamespace(StealthySession=FakeStealthySession)

        with patch.dict(sys.modules, {"scrapling.fetchers": fake_fetchers}):
            session_a = middleware._get_scrapling_session(request_a)
            self.assertIs(
                middleware._get_scrapling_session(request_a_again),
                session_a,
            )
            session_b = middleware._get_scrapling_session(request_b)
            session_c = middleware._get_scrapling_session(request_c)

        self.assertIsNot(session_a, session_b)
        self.assertIsNot(session_b, session_c)
        self.assertTrue(session_a.closed)
        self.assertEqual(
            session_b.options["proxy"],
            "http://proxy-a:8080",
        )
        self.assertEqual(
            session_c.options["proxy"],
            "http://proxy-b:8080",
        )

    def test_scrapling_is_reused_and_receives_timeout_headers_cookies(self):
        calls = []
        added_cookies = []

        class FakeSession:
            def fetch(self, url, **options):
                calls.append((url, options))
                page = SimpleNamespace(
                    context=SimpleNamespace(
                        add_cookies=lambda cookies: added_cookies.extend(cookies)
                    )
                )
                if options.get("page_setup"):
                    options["page_setup"](page)
                return SimpleNamespace(
                    url="https://example.com/final",
                    status=200,
                    headers={"Content-Type": "text/html; charset=utf-8"},
                    cookies={"from_browser": "yes"},
                    body=b"<html>ok</html>",
                )

        middleware = BackendRouterMiddleware(DummyCrawler())
        session = FakeSession()
        middleware._get_scrapling_session = lambda request: session
        request = Request(
            "https://example.com",
            headers={
                "Cookie": "sid=abc; theme=dark",
                "Referer": "https://referrer.example/",
                "X-Test": "yes",
            },
            meta={"solve_cloudflare": True},
        )

        response = middleware._download_scrapling(request, timeout=9)

        self.assertEqual(response.status, 200)
        self.assertEqual(calls[0][1]["timeout"], 9000)
        self.assertTrue(calls[0][1]["solve_cloudflare"])
        self.assertFalse(calls[0][1]["google_search"])
        self.assertEqual(calls[0][1]["extra_headers"]["X-Test"], "yes")
        self.assertEqual(
            response.headers["Set-Cookie"],
            b"from_browser=yes",
        )
        self.assertEqual(
            {(cookie["name"], cookie["value"]) for cookie in added_cookies},
            {("sid", "abc"), ("theme", "dark")},
        )


class ProxyPoolTests(unittest.TestCase):
    def test_proxy_provider_assigns_and_receives_health_reports(self):
        reports = []

        class Provider:
            def get_proxy(self, request, spider):
                return "http://user:pass@127.0.0.1:8080"

            def report_response(self, **kwargs):
                reports.append(("response", kwargs["response"].status))

            def report_exception(self, **kwargs):
                reports.append(("exception", type(kwargs["exception"]).__name__))

        middleware = ProxyPoolMiddleware(proxy_url=None, provider=Provider())
        request = Request("https://example.com")
        middleware.process_request(request)
        response = HtmlResponse(request.url, status=200, request=request)
        middleware.process_response(request, response)
        middleware.process_exception(request, RuntimeError("boom"))

        self.assertEqual(
            request.meta["proxy"],
            "http://user:pass@127.0.0.1:8080",
        )
        self.assertEqual(
            reports,
            [("response", 200), ("exception", "RuntimeError")],
        )

    def test_proxy_logging_mask_handles_credentials_and_ipv6(self):
        self.assertEqual(
            _mask_proxy_url("http://user:pass@127.0.0.1:8080"),
            "http://127.0.0.1:8080",
        )
        self.assertEqual(
            _mask_proxy_url("user:pass@[::1]:8080"),
            "[::1]:8080",
        )


if __name__ == "__main__":
    unittest.main()
