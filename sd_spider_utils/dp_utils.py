import threading
from DrissionPage import Chromium

def singleton(cls):
    instances = {}
    lock = threading.Lock()

    def get_instance(*args, **kwargs):
        if cls not in instances:
            with lock:
                if cls not in instances:
                    instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance

@singleton
class SingletonChromium(Chromium):
    ...

# TODO new_tab方法如果浏览器关了的话会报错，error，disconnect

def save_page(url,path=None,name=None,as_pdf=False):
    from DrissionPage import Chromium,ChromiumOptions
    co=ChromiumOptions()
    co.headless()
    chrome = Chromium(addr_or_opts=co)
    new_tab=chrome.new_tab()
    new_tab.get(url)
    new_tab.save(path=path,name=name,as_pdf=as_pdf)




def download_page(url, save_path, rename, page_session=None):
    """下载网页资源，html 页面保存为 html 文件，pdf 页面保存为 PDF 文件。

    :param url: 资源下载链接
    :param save_path: 本地保存目录路径，例如 'downloads' 或 './'
    :param rename: 重命名后的文件名，例如 'report.pdf'
    :param page_session: 可选，传入已实例化的 SessionPage 对象；不传则函数内自动实例化
    """
    # 组合完整文件路径，用于检查文件是否已存在
    import os

    file_path = os.path.join(save_path, rename)

    # 检查文件是否已存在
    if os.path.exists(file_path):
        print(f"文件已存在，跳过下载：{file_path}")
        return
    from DrissionPage import SessionPage
    # 初始化或复用传入的 SessionPage
    page_ = page_session if page_session else SessionPage()

    # 执行下载
    try:
        # 直接使用传入的保存目录和文件名
        res = page_.download(url, save_path=save_path, rename=rename)
        print(f"下载完成：{rename}，结果：{res}")
    except Exception as e:
        print(f"下载失败：{rename}，错误：{e}")

