import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scrapy.exceptions import NotSupported
from scrapy.http import Request
from scrapy.settings import Settings

from sd_spider_utils.middlewares import (
    BACKEND_META_KEY,
    BackendRouterMiddleware,
    TunnelProxyMiddleware,
    _backend_for_request,
    _build_response,
)


class DummyCrawler:
    def __init__(self, settings=None):
        self.settings = Settings(settings or {})
        self.signals = SimpleNamespace(connect=lambda *args, **kwargs: None)


class MiddlewareTests(unittest.TestCase):
    def test_backend_selection(self):
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
                    meta={BACKEND_META_KEY: "unknown"},
                )
            )

    def test_browser_backends_only_support_get(self):
        middleware = BackendRouterMiddleware(DummyCrawler())
        request = Request(
            "https://example.com",
            method="POST",
            meta={BACKEND_META_KEY: "dp"},
        )
        with self.assertRaises(NotSupported):
            middleware.process_request(request)

    def test_response_keeps_status_headers_and_body(self):
        request = Request("https://example.com/start")
        response = _build_response(
            request,
            "中文",
            status=302,
            url="https://example.com/final",
            headers={
                "Location": "/next",
                "Content-Encoding": "gzip",
            },
            backend="requests_go",
        )
        self.assertEqual(response.status, 302)
        self.assertEqual(response.url, "https://example.com/final")
        self.assertEqual(response.headers["Location"], b"/next")
        self.assertNotIn("Content-Encoding", response.headers)
        self.assertEqual(response.text, "中文")

    def test_requests_go_forwards_request_data(self):
        call = {}

        def fake_request(url, **kwargs):
            call.update(url=url, **kwargs)
            return SimpleNamespace(
                url="https://example.com/final",
                status_code=200,
                headers={"Content-Type": "text/html"},
                content=b"ok",
            )

        module = SimpleNamespace(request_with_requests_go=fake_request)
        middleware = BackendRouterMiddleware(DummyCrawler())
        request = Request(
            "https://example.com/start",
            method="POST",
            headers={"X-Test": "1"},
            body=b"data",
            meta={"proxy": "http://127.0.0.1:7890"},
        )
        with patch.dict(
            sys.modules,
            {"sd_spider_utils.request_utils": module},
        ):
            response = middleware._download_requests_go(request, 20)

        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["data"], b"data")
        self.assertEqual(call["proxy"], "http://127.0.0.1:7890")
        self.assertEqual(response.text, "ok")

    def test_dp_listen_requires_path(self):
        middleware = BackendRouterMiddleware(DummyCrawler())
        with self.assertRaises(ValueError):
            middleware._download_dp_listen(
                Request("https://example.com"),
                20,
            )

    def test_static_proxy_keeps_request_proxy(self):
        middleware = TunnelProxyMiddleware("http://default:8080")
        request = Request("https://example.com")
        middleware.process_request(request)
        self.assertNotIn("proxy", request.meta)

        request = Request("https://example.com", meta={"use_proxy": True})
        middleware.process_request(request)
        self.assertEqual(request.meta["proxy"], "http://default:8080")

        custom = Request(
            "https://example.com",
            meta={"use_proxy": True, "proxy": "http://custom:8080"},
        )
        middleware.process_request(custom)
        self.assertEqual(custom.meta["proxy"], "http://custom:8080")


if __name__ == "__main__":
    unittest.main()
