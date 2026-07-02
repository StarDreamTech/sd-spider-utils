import sys
import types
import unittest
from unittest.mock import Mock, patch

import sd_spider_utils
from sd_spider_utils.request_utils import (
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


if __name__ == "__main__":
    unittest.main()
