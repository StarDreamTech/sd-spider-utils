def request_with_requests_go(
    url,
    method="GET",
    headers=None,
    proxy=None,
    timeout=30,
    tls_config=None,
    **kwargs,
):
    """使用 requests-go 发起带浏览器 TLS 指纹的 HTTP 请求。

    :param url: 请求地址
    :param method: HTTP 请求方法
    :param headers: 请求头字典
    :param proxy: HTTP/HTTPS 共用的代理链接
    :param timeout: 请求超时秒数
    :param tls_config: TLS 指纹配置，默认使用最新版 Chrome
    :param kwargs: 传给 requests-go 的其他请求参数
    :return: requests-go Response 对象
    """
    if timeout <= 0:
        raise ValueError("timeout 必须大于 0")

    import requests_go

    if tls_config is None:
        tls_config = requests_go.tls_config.TLS_CHROME_LATEST
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    return requests_go.request(
        method=method.upper(),
        url=url,
        headers=headers,
        timeout=timeout,
        tls_config=tls_config,
        **kwargs,
    )


def request_with_curl_cffi(
    url,
    method="GET",
    headers=None,
    proxy=None,
    timeout=30,
    impersonate="chrome",
    **kwargs,
):
    """使用 curl_cffi 发起支持浏览器指纹模拟的 HTTP 请求。

    :param url: 请求地址
    :param method: HTTP 请求方法
    :param headers: 请求头字典
    :param proxy: HTTP/HTTPS 共用的代理链接
    :param timeout: 请求超时秒数
    :param impersonate: 浏览器指纹，chrome 表示当前版本支持的最新版 Chrome
    :param kwargs: 传给 curl_cffi.requests 的其他请求参数
    :return: curl_cffi Response 对象
    """
    if timeout <= 0:
        raise ValueError("timeout 必须大于 0")

    from curl_cffi import requests

    return requests.request(
        method=method.upper(),
        url=url,
        headers=headers,
        proxy=proxy,
        timeout=timeout,
        impersonate=impersonate,
        **kwargs,
    )
