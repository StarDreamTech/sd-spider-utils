import re


def normalize_text(text):
    """
    文本标准化：转换为标准形式，并处理特殊字符。
    - 使用 NFKC 进行 Unicode 标准化。
    - 替换不间断空格（\xa0）为普通空格。
    - 移除其他不可见的空白字符，如换行符、回车符、制表符等。
    - 移除多余的空格，确保文本整洁。
    """
    import unicodedata

    if not isinstance(text, str):
        return text  # 如果输入不是字符串，直接返回

    # Unicode 标准化
    text = unicodedata.normalize("NFKC", text)
    # 移除多余的空格（多个空格替换为一个空格）
    text = re.sub(r"\s+", " ", text)
    # 去除首尾空格
    text = text.strip()
    return text


def normalize_obj(obj):
    """
    递归标准化所有文本字段
    """
    if isinstance(obj, dict):
        return {k: normalize_obj(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [normalize_obj(v) for v in obj]
    elif isinstance(obj, str):
        return normalize_text(obj)
    else:
        return obj


def clean_text(text: str):
    # 替换非断空白符为普通空格
    text = text.replace("\xa0", " ")
    # 移除字符串两端的空格
    text = text.strip()
    # 替换多个空格为单个空格
    text = " ".join(text.split())
    # 移除多余的标点符号，例如连续的逗号或逗号后面紧跟空格
    text = text.replace(" ,", ",").replace(", ,", ",")
    return text


def remove_extra_spaces(text: str) -> str:
    """
    移除字符串中的多个空格为单个空格。
    :param text: 输入字符串
    :return: 处理后的字符串
    # 示例
    text = "This   is   a   text     with  multiple     spaces."
    cleaned_text = remove_extra_spaces(text)
    print(cleaned_text)  # 输出: "This is a text with multiple spaces."
    """
    return " ".join(text.split())


def remove_extra_blank_spaces(text: str) -> str:
    """
    移除字符串中的多余空白字符（空格、制表符、换行符等），
    并将其替换为单个空格。

    :param text: 输入字符串
    :return: 处理后的字符串

    # 示例
    text = "This   is   a   text     with  multiple     spaces."
    cleaned_text = remove_extra_spaces(text)
    print(cleaned_text)  # 输出: "This is a text with multiple spaces."
    """
    import re

    return re.sub(r"\s+", " ", text).strip()


def contains_chinese(text: str) -> bool:
    """
    使用正则表达式检查是否包含汉字
    """
    import re

    return bool(re.search(r"[\u4e00-\u9fa5]", text))


def contains_date(text: str) -> bool:
    """
    使用正则表达式检查是否包含类似 '2022年03月30日' 的日期
    """
    import re

    return bool(re.search(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?", text))


if __name__ == "__main__":
    text = "This   is   a   text     with  multiple     spaces."
    # 使用正则表达式替换一个或多个空白字符（包括空格、制表符、换行符等）为一个空格
    cleaned_text = re.sub(r"\s+", " ", text).strip()

    print(cleaned_text)

    text1 = "This is a te{||||  nmakldnsjdmksxm  15651654 st.把那家伙半小时·"
    text2 = "这是一个测试。"

    print(contains_chinese(text1))  # False
    print(contains_chinese(text2))  # True

    # 测试
    text1 = "今天是2022年03月30日，天气晴。"
    text2 = "这是一个没有日期的文本。"

    print(contains_date(text1))  # True
    print(contains_date(text2))  # False
    text = "Ｃａｆé['S.\u2009M. Koksbang\xa0', 'S.\u2009M. Koksbang']"  # 包含全角字符和组合字符
    normalize_text(text)
