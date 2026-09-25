import re
import unicodedata

_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
_DATE_RE = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?")


def normalize_text(text):
    """使用 NFKC 规范化字符串，并把连续空白压缩为一个空格。

    :param text: 待规范化的值；非字符串会原样返回
    :return: 规范化后的值
    """
    if not isinstance(text, str):
        return text
    return " ".join(unicodedata.normalize("NFKC", text).split())


def normalize_obj(obj):
    """递归规范化字典和列表中的字符串。

    :param obj: 字典、列表、字符串或其他值
    :return: 规范化后的对象
    """
    if isinstance(obj, dict):
        return {key: normalize_obj(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [normalize_obj(value) for value in obj]
    return normalize_text(obj)


def clean_text(text: str) -> str:
    """压缩空白并清理逗号前的多余空格。

    :param text: 待清理的文本
    :return: 清理后的文本
    """
    return " ".join(text.replace(" ,", ",").replace(", ,", ",").split())


def remove_extra_spaces(text: str) -> str:
    """把连续空白字符压缩为一个空格。

    :param text: 待处理的文本
    :return: 处理后的文本
    """
    return " ".join(text.split())


def contains_chinese(text: str) -> bool:
    """判断文本是否包含汉字。

    :param text: 待检查的文本
    :return: 包含汉字时返回 True
    """
    return bool(_CHINESE_RE.search(text))


def contains_date(text: str) -> bool:
    """判断文本是否包含年月日格式的日期。

    :param text: 待检查的文本
    :return: 包含年月日格式日期时返回 True
    """
    return bool(_DATE_RE.search(text))
