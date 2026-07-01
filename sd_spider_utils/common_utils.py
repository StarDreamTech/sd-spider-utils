_BOOL_VALUES = {
    "y": True,
    "yes": True,
    "t": True,
    "true": True,
    "on": True,
    "1": True,
    "n": False,
    "no": False,
    "f": False,
    "false": False,
    "off": False,
    "0": False,
}


def strtobool(value) -> bool:
    """把常见的真假字符串或数字转换为布尔值。

    :param value: 待转换的字符串、数字或布尔值
    :return: 转换后的布尔值
    :raises ValueError: value 无法识别时抛出
    """
    try:
        return _BOOL_VALUES[str(value).strip().lower()]
    except KeyError as exc:
        raise ValueError(f"{value!r} 不是有效的布尔值") from exc
