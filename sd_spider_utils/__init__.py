"""sd_spider_utils 的常用公开 API。"""

from importlib import import_module

from .common_utils import strtobool
from .data_utils import data2excel, json2excel, load_json_data
from .datetime_utils import extract_dates
from .parse_utils import get_text_bs4, get_text_scrapy, get_text_xpath
from .spider_demos import xpath_demo
from .text_utils import (
    clean_text,
    contains_chinese,
    contains_date,
    normalize_obj,
    normalize_text,
    remove_extra_blank_spaces,
    remove_extra_spaces,
)

# 兼容旧版包级名称，实际实现只保留一份。
datetime_clean_text = clean_text
datetime_contains_chinese = contains_chinese
datetime_contains_date = contains_date

_LAZY_EXPORTS = {
    name: (".dp_utils", name)
    for name in (
        "BrowserManager",
        "browser_manager",
        "close_all_browsers",
        "close_browser",
        "download_page",
        "get_browser",
        "get_html_from_chrome",
        "save_page",
        "singleton",
    )
}
_LAZY_EXPORTS["request_with_requests_go"] = (
    ".request_utils",
    "request_with_requests_go",
)


def __getattr__(name):
    """按需加载可选依赖工具，避免基础安装被额外依赖绑死。"""
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "BrowserManager",
    "browser_manager",
    "clean_text",
    "close_all_browsers",
    "close_browser",
    "contains_chinese",
    "contains_date",
    "data2excel",
    "datetime_clean_text",
    "datetime_contains_chinese",
    "datetime_contains_date",
    "download_page",
    "extract_dates",
    "get_browser",
    "get_html_from_chrome",
    "get_text_bs4",
    "get_text_scrapy",
    "get_text_xpath",
    "json2excel",
    "load_json_data",
    "normalize_obj",
    "normalize_text",
    "remove_extra_blank_spaces",
    "remove_extra_spaces",
    "request_with_requests_go",
    "save_page",
    "singleton",
    "strtobool",
    "xpath_demo",
]
