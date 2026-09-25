import atexit
import logging
import time

logger = logging.getLogger(__name__)

CHROME_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
    "accept": "*/*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# Vercel 安全验证页的提示文案（中英文）
CHECKPOINT_WAITING = ("我们正在验证您的浏览器", "We're verifying your browser")
CHECKPOINT_FAILED = ("无法验证您的浏览器", "Failed to verify your browser")


def cffi_get(url, headers=None, impersonate="chrome", timeout=30, **kwargs):
    """使用 curl_cffi 模拟 Chrome 指纹发送 GET 请求。

    :param url: 请求地址
    :param headers: 请求头字典，默认使用 Chrome 请求头
    :param impersonate: 浏览器指纹
    :param timeout: 请求超时秒数
    :param kwargs: 传给 curl_cffi.requests.get 的其他参数
    :return: Response 对象；请求失败时返回 None
    """
    from curl_cffi import requests

    try:
        return requests.get(
            url,
            headers=headers or CHROME_HEADERS,
            impersonate=impersonate,
            timeout=timeout,
            **kwargs,
        )
    except requests.RequestsError as e:
        logger.error("cffi GET 请求失败 %s: %s", url, e)
        return None


_tab = None


def _get_tab():
    """获取全局复用的浏览器标签页，进程退出时自动关闭浏览器。"""
    global _tab
    if _tab is None:
        from DrissionPage import Chromium, ChromiumOptions

        browser = Chromium(ChromiumOptions().auto_port())
        atexit.register(browser.quit)
        _tab = browser.new_tab()
    return _tab


def fetch_text_with_browser(url, retries=10, interval=1):
    """用浏览器打开页面，等待通过 Vercel 安全验证后返回页面文本。

    :param url: 目标网页地址
    :param retries: 最多检查次数
    :param interval: 每次检查间隔秒数
    :return: 页面 body 文本；未通过验证时返回 None
    """
    tab = _get_tab()
    tab.get(url)
    for _ in range(retries):
        text = tab.ele("tag:body").text
        if any(tip in text for tip in CHECKPOINT_FAILED):
            tab.refresh()
        elif not any(tip in text for tip in CHECKPOINT_WAITING):
            return text
        time.sleep(interval)
    logger.warning("未通过浏览器验证: %s", url)
    return None
