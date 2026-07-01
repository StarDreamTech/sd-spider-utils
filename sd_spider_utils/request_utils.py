def request_with_requests_go(
    url,
    method="GET",
    headers=None,
    timeout=30,
    tls_config=None,
    **kwargs,
):
    """使用 requests-go 发起带浏览器 TLS 指纹的 HTTP 请求。

    :param url: 请求地址
    :param method: HTTP 请求方法
    :param headers: 请求头字典
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
    return requests_go.request(
        method=method.upper(),
        url=url,
        headers=headers,
        timeout=timeout,
        tls_config=tls_config,
        **kwargs,
    )
