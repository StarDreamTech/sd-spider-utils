import sys
import types
import unittest
from unittest.mock import Mock, patch

import sd_spider_utils
from sd_spider_utils.request_utils import (
    fetch_text_with_browser,
    request_with_curl_cffi,
    request_with_requests_go,
)


class RequestsGoTests(unittest.TestCase):
    def test_request_uses_default_chrome_tls(self):
        response = object()
        request = Mock(return_value=response)
        chrome_tls = object()
        module = types.SimpleNamespace(
            request=request,
            tls_config=types.SimpleNamespace(TLS_CHROME_LATEST=chrome_tls),
        )

        with patch.dict(sys.modules, {"requests_go": module}):
            result = request_with_requests_go(
                "https://example.com",
                headers={"User-Agent": "Chrome"},
                proxy="http://127.0.0.1:7890",
                verify=False,
            )

        self.assertIs(result, response)
        self.assertIs(
            sd_spider_utils.request_with_requests_go,
            request_with_requests_go,
        )
        request.assert_called_once_with(
            method="GET",
            url="https://example.com",
            headers={"User-Agent": "Chrome"},
            timeout=30,
            tls_config=chrome_tls,
            proxies={
                "http": "http://127.0.0.1:7890",
                "https": "http://127.0.0.1:7890",
            },
            verify=False,
        )

    def test_timeout_must_be_positive(self):
        with self.assertRaises(ValueError):
            request_with_requests_go("https://example.com", timeout=0)

    def test_curl_cffi_uses_latest_chrome_by_default(self):
        response = object()
        request = Mock(return_value=response)
        module = types.SimpleNamespace(request=request)

        curl_cffi = types.SimpleNamespace(requests=module)
        with patch.dict(sys.modules, {"curl_cffi": curl_cffi}):
            result = request_with_curl_cffi(
                "https://example.com",
                headers={"User-Agent": "Chrome"},
                proxy="http://127.0.0.1:7890",
                verify=False,
            )

        self.assertIs(result, response)
        self.assertIs(
            sd_spider_utils.request_with_curl_cffi,
            request_with_curl_cffi,
        )
        request.assert_called_once_with(
            method="GET",
            url="https://example.com",
            headers={"User-Agent": "Chrome"},
            proxy="http://127.0.0.1:7890",
            timeout=30,
            impersonate="chrome",
            verify=False,
        )

    def test_curl_cffi_can_disable_impersonation(self):
        request = Mock()
        module = types.SimpleNamespace(request=request)

        curl_cffi = types.SimpleNamespace(requests=module)
        with patch.dict(sys.modules, {"curl_cffi": curl_cffi}):
            request_with_curl_cffi("https://example.com", impersonate=None)

        self.assertIsNone(request.call_args.kwargs["impersonate"])

    def test_curl_cffi_timeout_must_be_positive(self):
        with self.assertRaises(ValueError):
            request_with_curl_cffi("https://example.com", timeout=0)


class FakeTab:
    def __init__(self, texts):
        self.texts = list(texts)
        self.refreshed = 0
        self.closed = False

    def get(self, url):
        self.url = url

    def ele(self, locator):
        return types.SimpleNamespace(text=self.texts.pop(0))

    def refresh(self):
        self.refreshed += 1

    def close(self):
        self.closed = True


class FetchTextWithBrowserTests(unittest.TestCase):
    def fetch(self, texts, **kwargs):
        tab = FakeTab(texts)
        browser = types.SimpleNamespace(new_tab=lambda: tab)
        with patch("sd_spider_utils.dp_utils.get_browser", return_value=browser):
            with patch("sd_spider_utils.request_utils.time.sleep"):
                return fetch_text_with_browser("https://example.com", **kwargs), tab

    def test_waits_until_checkpoint_passed(self):
        result, tab = self.fetch(
            ["We're verifying your browser", "无法验证您的浏览器", "正文"]
        )

        self.assertEqual(result, "正文")
        self.assertEqual(tab.refreshed, 1)
        self.assertTrue(tab.closed)
        self.assertIs(
            sd_spider_utils.fetch_text_with_browser,
            fetch_text_with_browser,
        )

    def test_returns_none_when_checkpoint_never_passes(self):
        result, tab = self.fetch(["我们正在验证您的浏览器"] * 3, retries=3)

        self.assertIsNone(result)
        self.assertTrue(tab.closed)


if __name__ == "__main__":
    unittest.main()
