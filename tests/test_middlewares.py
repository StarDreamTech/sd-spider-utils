import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scrapy.exceptions import DownloadTimeoutError, NotSupported
from scrapy.http import HtmlResponse, Request
from scrapy.settings import Settings

from sd_spider_utils.middlewares import (
    BACKEND_FALLBACKS_META_KEY,
    BACKEND_META_KEY,
    BackendRouterMiddleware,
    TunnelProxyMiddleware,
    _backend_error,
    _backend_for_request,
    _scrapy_response,
)


class DummyCrawler:
    def __init__(self, settings=None):
        self.settings = Settings(settings or {})
        self.spider = None
        self.signals = SimpleNamespace(connect=lambda *args, **kwargs: None)


class MiddlewareTests(unittest.TestCase):
    def test_backend_selection_is_explicit(self):
        self.assertIsNone(_backend_for_request(Request("https://example.com")))
        for backend in ("scrapy", "requests_go", "dp", "dp_listen", "scrapling"):
            request = Request(
                "https://example.com",
                meta={BACKEND_META_KEY: backend},
            )
            self.assertEqual(_backend_for_request(request), backend)
        with self.assertRaises(ValueError):
            _backend_for_request(
                Request(
                    "https://example.com",
                    meta={BACKEND_META_KEY: "requests-go"},
                )
            )

    def test_browser_backends_reject_non_get(self):
        middleware = BackendRouterMiddleware(DummyCrawler())
        request = Request(
            "https://example.com",
            method="POST",
            meta={BACKEND_META_KEY: "scrapling"},
        )
        with self.assertRaises(NotSupported):
            middleware.process_request(request)

    def test_response_keeps_http_information(self):
        request = Request("https://example.com/start")
        response = _scrapy_response(
            request,
            "requests_go",
            "https://example.com/final",
            302,
            {
                "Content-Type": "text/html; charset=gb18030",
                "Content-Encoding": "gzip",
                "Location": "/next",
                "Set-Cookie": "sid=abc; Path=/",
            },
            "<p>中文</p>".encode("gb18030"),
        )
        self.assertEqual(
            (response.status, response.url), (302, "https://example.com/final")
        )
        self.assertEqual(response.headers["Location"], b"/next")
        self.assertEqual(response.headers["Set-Cookie"], b"sid=abc; Path=/")
        self.assertNotIn("Content-Encoding", response.headers)
        self.assertIn("中文", response.text)

        rendered = _scrapy_response(
            request,
            "dp",
            request.url,
            200,
            {"Content-Type": "text/html; charset=gbk"},
            "<p>中文</p>",
        )
        self.assertEqual(rendered.encoding, "utf-8")
        self.assertIn("中文", rendered.text)

    def test_requests_go_forwards_request_semantics(self):
        calls = []

        def fake_request(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                url="https://example.com/final",
                status_code=307,
                headers={"Location": "/again", "Set-Cookie": "sid=next"},
                content=b"redirect",
            )

        module = SimpleNamespace(
            request=fake_request,
            tls_config=SimpleNamespace(TLS_CHROME_LATEST=object()),
        )
        middleware = BackendRouterMiddleware(DummyCrawler())
        request = Request(
            "https://example.com/start",
            method="PUT",
            headers={"Cookie": "sid=abc", "Content-Length": "3"},
            body=b"abc",
            meta={"proxy": "http://127.0.0.1:8080"},
        )
        with patch.dict(sys.modules, {"requests_go": module}):
            response = middleware._download_requests_go(request, 5)

        sent = calls[0]
        self.assertEqual((sent["method"], sent["data"]), ("PUT", b"abc"))
        self.assertFalse(sent["allow_redirects"])
        self.assertEqual(sent["headers"]["Cookie"], "sid=abc")
        self.assertNotIn("Content-Length", sent["headers"])
        self.assertEqual(response.status, 307)

    def test_retry_errors_and_backend_fallback(self):
        self.assertIsInstance(
            _backend_error("requests_go", RuntimeError("timed out")),
            DownloadTimeoutError,
        )
        middleware = BackendRouterMiddleware(DummyCrawler())
        request = Request(
            "https://example.com",
            meta={
                BACKEND_FALLBACKS_META_KEY: [
                    "scrapy",
                    "requests_go",
                ]
            },
        )
        response = HtmlResponse(request.url, status=403, request=request)
        retry = middleware.process_response(request, response)
        self.assertEqual(retry.meta[BACKEND_META_KEY], "requests_go")
        self.assertTrue(retry.dont_filter)

    def test_scrapling_sessions_are_isolated(self):
        created = []

        class FakeSession:
            def __init__(self, **options):
                self.options = options
                created.append(self)

            def start(self):
                pass

        module = SimpleNamespace(StealthySession=FakeSession)
        middleware = BackendRouterMiddleware(DummyCrawler())
        account_a = Request(
            "https://example.com",
            meta={"cookiejar": "a", "proxy": "http://proxy-a:8080"},
        )
        account_b = Request(
            "https://example.com",
            meta={"cookiejar": "b", "proxy": "http://proxy-a:8080"},
        )
        scrapling = SimpleNamespace(fetchers=module)
        with patch.dict(
            sys.modules,
            {"scrapling": scrapling, "scrapling.fetchers": module},
        ):
            first = middleware._scrapling_session(account_a)
            self.assertIs(first, middleware._scrapling_session(account_a.copy()))
            second = middleware._scrapling_session(account_b)

        self.assertIsNot(first, second)
        self.assertEqual(len(created), 2)

    def test_static_proxy_does_not_override_request_proxy(self):
        middleware = TunnelProxyMiddleware("http://default:8080")
        request = Request("https://example.com")
        middleware.process_request(request)
        self.assertEqual(request.meta["proxy"], "http://default:8080")

        custom = Request(
            "https://example.com",
            meta={"proxy": "http://custom:8080"},
        )
        middleware.process_request(custom)
        self.assertEqual(custom.meta["proxy"], "http://custom:8080")


if __name__ == "__main__":
    unittest.main()
