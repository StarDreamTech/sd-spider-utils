import threading
from pathlib import Path


def singleton(cls):
    """把类包装成线程安全、可重置的单例构造器。

    :param cls: 需要包装的类
    :return: 带 reset_instance 属性的单例构造器
    """
    instance = None
    lock = threading.Lock()

    def get_instance(*args, **kwargs):
        nonlocal instance
        if instance is None:
            with lock:
                if instance is None:
                    instance = cls(*args, **kwargs)
        return instance

    def reset_instance():
        nonlocal instance
        with lock:
            current, instance = instance, None
        if current and hasattr(current, "quit"):
            try:
                current.quit()
            except Exception:
                pass

    get_instance.reset_instance = reset_instance
    return get_instance


class BrowserManager:
    """按类型维护 Chromium 实例，同一类型只创建一个浏览器。"""

    def __init__(self):
        self._browsers = {}
        self._lock = threading.Lock()

    def get(self, browser_type="default", browser_options=None, headless=True):
        """获取指定类型的浏览器，不存在时按当前配置创建。

        :param browser_type: 浏览器类型，也是单例实例的唯一标识
        :param browser_options: DrissionPage ChromiumOptions 配置
        :param headless: 未传 browser_options 时是否使用无头模式
        :return: 指定类型的 Chromium 实例
        """
        with self._lock:
            if browser_type not in self._browsers:
                from DrissionPage import Chromium, ChromiumOptions

                options = (
                    browser_options
                    if browser_options is not None
                    else ChromiumOptions().headless(headless).auto_port()
                )
                self._browsers[browser_type] = Chromium(options)
            return self._browsers[browser_type]

    def close(self, browser_type="default"):
        """关闭并移除指定类型的浏览器。

        :param browser_type: 要关闭的浏览器类型
        :return: 找到并关闭浏览器时返回 True
        """
        with self._lock:
            browser = self._browsers.pop(browser_type, None)
        if browser is None:
            return False
        browser.quit()
        return True

    def close_all(self):
        """关闭并移除全部浏览器实例。"""
        with self._lock:
            browsers, self._browsers = list(self._browsers.values()), {}
        for browser in browsers:
            browser.quit()


browser_manager = BrowserManager()


def get_browser(browser_type="default", browser_options=None, headless=True):
    """获取按类型复用的 Chromium 浏览器。

    :param browser_type: 浏览器类型，也是单例实例的唯一标识
    :param browser_options: 首次创建该类型时使用的 ChromiumOptions
    :param headless: 未传 browser_options 时是否使用无头模式
    :return: 指定类型的 Chromium 实例
    """
    return browser_manager.get(browser_type, browser_options, headless)


def close_browser(browser_type="default"):
    """关闭指定类型的浏览器。

    :param browser_type: 要关闭的浏览器类型
    :return: 找到并关闭浏览器时返回 True
    """
    return browser_manager.close(browser_type)


def close_all_browsers():
    """关闭全部由 BrowserManager 创建的浏览器。"""
    browser_manager.close_all()


def save_page(
    url,
    path=None,
    name=None,
    as_pdf=False,
    headless=True,
    browser_type="default",
    browser_options=None,
):
    """使用指定类型的单例浏览器保存网页或 PDF。

    :param url: 目标网页地址
    :param path: 保存目录
    :param name: 保存文件名
    :param as_pdf: 是否保存为 PDF
    :param headless: 是否使用无头浏览器
    :param browser_type: 浏览器类型；同一类型复用同一个实例
    :param browser_options: 首次创建该类型时使用的 ChromiumOptions
    :return: DrissionPage 的保存结果
    """
    browser = get_browser(browser_type, browser_options, headless)
    tab = browser.new_tab()
    try:
        tab.get(url)
        return tab.save(path=path, name=name, as_pdf=as_pdf)
    finally:
        tab.close()


def download_page(url, save_path, rename, page_session=None):
    """下载网页资源；目标文件已存在时直接跳过。

    :param url: 资源地址
    :param save_path: 保存目录
    :param rename: 保存文件名
    :param page_session: 可复用的 DrissionPage SessionPage
    :return: DrissionPage 的下载结果；文件已存在时返回 None
    """
    target = Path(save_path) / rename
    if target.exists():
        return None

    if page_session is None:
        from DrissionPage import SessionPage

        page_session = SessionPage()
    return page_session.download(
        url,
        save_path=str(target.parent),
        rename=target.name,
    )


def get_html_from_chrome(
    url,
    port=None,
    mode=None,
    proxy=None,
    wait_api=None,
    wait_api_timeout=20,
):
    """获取浏览器渲染后的 HTML，可等待指定网络请求完成。

    :param url: 目标网页地址
    :param port: 可选的 Chrome 调试端口
    :param mode: 页面加载模式，例如 normal、eager 或 none
    :param proxy: 代理地址
    :param wait_api: 需要等待的接口路径或关键字
    :param wait_api_timeout: 等待接口的超时秒数
    :return: 浏览器渲染后的 HTML
    """
    from DrissionPage import Chromium, ChromiumOptions

    options = ChromiumOptions()
    if mode:
        options.set_load_mode(mode)
    if port:
        options.set_local_port(port)
    if proxy:
        options.set_proxy(proxy)

    browser = Chromium(options) if mode or port or proxy else Chromium()
    tab = browser.new_tab()
    try:
        if wait_api:
            tab.listen.start(wait_api)
        tab.get(url)
        if wait_api:
            tab.listen.wait(timeout=wait_api_timeout)
        return tab.html
    finally:
        tab.close()
