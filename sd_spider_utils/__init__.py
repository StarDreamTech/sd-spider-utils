"""包级导出，便于直接从 sd_spider_utils 导入常用函数。"""

from importlib import import_module

from .common_utils import strtobool
from .data_utils import data2excel, json2excel, load_json_data
from .datetime_utils import (
    clean_text as datetime_clean_text,
    contains_chinese as datetime_contains_chinese,
    contains_date as datetime_contains_date,
    extract_dates,
)
from .parse_utils import get_text_bs4, get_text_scrapy, get_text_xpath
from .spider_demos import xpath_demo
from .text_utils import (
    clean_text,
    contains_chinese,
    contains_date,
    normalize_text,
    remove_extra_blank_spaces,
    remove_extra_spaces,
)

_LAZY_EXPORTS = {
    "download_page": (".dp_utils", "download_page"),
    "save_page": (".dp_utils", "save_page"),
    "singleton": (".dp_utils", "singleton"),
}


def __getattr__(name):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = _LAZY_EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


__all__ = [
    "clean_text",
    "contains_chinese",
    "contains_date",
    "data2excel",
    "datetime_clean_text",
    "datetime_contains_chinese",
    "datetime_contains_date",
    "download_page",
    "extract_dates",
    "get_text_bs4",
    "get_text_scrapy",
    "get_text_xpath",
    "json2excel",
    "load_json_data",
    "normalize_text",
    "remove_extra_blank_spaces",
    "remove_extra_spaces",
    "save_page",
    "singleton",
    "strtobool",
    "xpath_demo",
]
