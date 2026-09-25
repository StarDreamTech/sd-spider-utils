def xpath_demo():
    """打印常用 Scrapy XPath 写法示例。"""
    print(
        """
    类名为 cpython666 的节点 response.xpath("//*[@class='cpython666']")
    类名以 cpython666 开头的节点 response.xpath("//*[starts-with(@class, 'cpython666')]")
    文本包含 cpython666 的h2标签的后续兄弟p标签 response.xpath("//h2[contains(string(.), 'cpython666')]/following-sibling::p")
    """
    )


if __name__ == "__main__":
    xpath_demo()
