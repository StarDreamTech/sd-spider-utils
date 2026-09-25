import sys
import types
import unittest
from unittest.mock import patch

from sd_spider_utils import dp_utils
from sd_spider_utils.dp_utils import BrowserManager


class FakeOptions:
    def headless(self, value=True):
        self.headless_value = value
        return self

    def auto_port(self):
        return self


class FakeTab:
    def __init__(self):
        self.closed = False

    def get(self, url):
        self.url = url

    def save(self, **kwargs):
        return kwargs

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, options):
        self.options = options
        self.closed = False

    def new_tab(self):
        return FakeTab()

    def quit(self):
        self.closed = True


class BrowserManagerTests(unittest.TestCase):
    def setUp(self):
        module = types.SimpleNamespace(
            Chromium=FakeBrowser,
            ChromiumOptions=FakeOptions,
        )
        self.drission_patch = patch.dict(sys.modules, {"DrissionPage": module})
        self.drission_patch.start()
        self.manager = BrowserManager()

    def tearDown(self):
        self.manager.close_all()
        self.drission_patch.stop()

    def test_browser_is_singleton_per_type(self):
        default = self.manager.get()
        self.assertIs(default, self.manager.get())
        self.assertIsNot(default, self.manager.get("proxy", FakeOptions()))

    def test_browser_can_be_closed_externally(self):
        browser = self.manager.get("proxy")
        self.assertTrue(self.manager.close("proxy"))
        self.assertTrue(browser.closed)
        self.assertIsNot(browser, self.manager.get("proxy"))
        self.assertFalse(self.manager.close("missing"))

    def test_save_page_reuses_browser_until_external_close(self):
        with patch.object(dp_utils, "browser_manager", self.manager):
            dp_utils.save_page("https://example.com", browser_type="archive")
            browser = self.manager.get("archive")
            dp_utils.save_page("https://example.org", browser_type="archive")
            self.assertFalse(browser.closed)
            self.assertTrue(dp_utils.close_browser("archive"))
            self.assertTrue(browser.closed)


if __name__ == "__main__":
    unittest.main()
