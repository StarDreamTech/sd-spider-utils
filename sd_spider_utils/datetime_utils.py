import re
from datetime import datetime

from .text_utils import clean_text, contains_chinese, contains_date

_DATE_PARTS_RE = re.compile(
    r"(?P<year>\d{4})[-/年](?P<month>\d{1,2})[-/月](?P<day>\d{1,2})日?"
)


def extract_dates(text: str) -> list[datetime]:
    """提取文本中的年月日日期，自动忽略不存在的日期。

    :param text: 待检查的文本
    :return: 提取到的 datetime 对象列表
    """
    dates = []
    for match in _DATE_PARTS_RE.finditer(text):
        try:
            dates.append(
                datetime(
                    int(match["year"]),
                    int(match["month"]),
                    int(match["day"]),
                )
            )
        except ValueError:
            continue
    return dates


__all__ = ["clean_text", "contains_chinese", "contains_date", "extract_dates"]
