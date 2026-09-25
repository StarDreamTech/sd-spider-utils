def get_text_bs4(html: str, remove_blank_lines: bool = False) -> str:
    """使用 BeautifulSoup 提取 HTML 文本。

    :param html: HTML 字符串
    :param remove_blank_lines: 是否移除空行并清理每行首尾空白
    :return: 提取后的文本
    """
    from bs4 import BeautifulSoup

    text = BeautifulSoup(html, "html.parser").get_text()
    if remove_blank_lines:
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return text.strip()


def get_text_xpath(html: str) -> list[str]:
    """使用 lxml XPath 返回 HTML 中的全部文本节点。

    :param html: HTML 字符串
    :return: 文本节点列表
    """
    from lxml import etree

    return etree.HTML(html).xpath("//text()")


def get_text_scrapy(html: str) -> str:
    """使用 Scrapy Selector 提取并拼接全部文本节点。

    :param html: HTML 字符串
    :return: 拼接后的文本
    """
    from scrapy import Selector

    return "".join(Selector(text=html).xpath("//text()").getall())
