"""从指定 env 文件只读查询 Codex 用量、重置时间及重置卡张数和过期时间。"""

import argparse
import base64
import binascii
from datetime import datetime, timezone
from getpass import getpass
import json
import math
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
RESET_CREDITS_URL = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
ENCODING_PREFIX = "base64rev:"


def encode_token(value):
    """返回带格式前缀的 Base64 倒序值（仅混淆）。"""
    return (
        ENCODING_PREFIX + base64.b64encode(value.encode("utf-8")).decode("ascii")[::-1]
    )


def decode_token(value):
    """还原带前缀的混淆值；无前缀时按原文处理。"""
    if not value.startswith(ENCODING_PREFIX):
        return value
    try:
        return base64.b64decode(
            value.removeprefix(ENCODING_PREFIX)[::-1], validate=True
        ).decode("utf-8")
    except (ValueError, binascii.Error) as exc:
        raise ValueError("无效的 base64rev 编码") from exc


def load_accounts(env_file):
    """解析单行 env 赋值，不执行代码、不展开变量、不读取进程环境。"""
    accounts = {}
    seen = set()
    for number, line in enumerate(
        Path(env_file).expanduser().read_text(encoding="utf-8-sig").splitlines(), 1
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        assignment = re.fullmatch(
            r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line
        )
        if not assignment:
            raise ValueError(f"env 第 {number} 行不是有效的 KEY=VALUE")
        key, value = assignment.groups()
        match = re.fullmatch(
            r"CODEX(?:_([A-Za-z0-9_]+))?_(ACCESS_TOKEN|ACCOUNT_ID)", key
        )
        if match:
            name, field = match.groups()
        else:
            match = re.fullmatch(
                r"CODEX_(ACCESS_TOKEN|ACCOUNT_ID)_([A-Za-z0-9_]+)", key
            )
            if not match:
                continue
            field, name = match.groups()
        identity = (name, field)
        if identity in seen:
            raise ValueError(f"env 第 {number} 行包含重复的账号字段")
        seen.add(identity)
        if value.startswith(("'", '"')):
            quoted = re.fullmatch(r"(['\"])(.*?)\1\s*(?:#.*)?", value)
            if not quoted:
                raise ValueError(f"env 第 {number} 行引号未闭合或存在多余内容")
            value = quoted.group(2)
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        try:
            value = decode_token(value)
        except ValueError:
            raise ValueError(f"env 第 {number} 行的混淆值无效") from None
        if not value or any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise ValueError(f"env 第 {number} 行的凭据为空或含非法字符")
        # 用 None 区分无名称账号和名为 DEFAULT 的账号。
        accounts.setdefault(name, {})[field.lower()] = value
    if not accounts:
        raise ValueError("env 中未找到 CODEX_ACCESS_TOKEN / CODEX_ACCOUNT_ID 账号对")
    for name, pair in accounts.items():
        if set(pair) != {"access_token", "account_id"}:
            raise ValueError(f"账号 {name or '(默认)'} 缺少 ACCESS_TOKEN 或 ACCOUNT_ID")
    return accounts


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 防止带凭据的请求被重定向到其他地址。
        return None


def _get_json(url, access_token, account_id, timeout):
    # 只允许这两个查询地址；不提供兑换重置卡的请求方法或入口。
    if url not in (USAGE_URL, RESET_CREDITS_URL):
        raise ValueError("仅允许访问只读查询接口")
    request = Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {access_token}",
            "ChatGPT-Account-Id": account_id,
            "Accept": "application/json",
            "User-Agent": "sd-spider-utils/codex-usage",
        },
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        hints = {
            401: "登录令牌失效，请重新登录并更新 env 中的账号对",
            403: "访问被拒绝，请检查账号权限或网络环境",
            429: "查询过于频繁，请稍后重试",
        }
        raise ValueError(
            f"HTTP {exc.code}：{hints.get(exc.code, '查询失败')}"
        ) from None
    except (URLError, OSError):
        raise ValueError("连接失败或超时，请检查网络及 HTTPS_PROXY 设置") from None
    except (ValueError, UnicodeError):
        raise ValueError("查询接口未返回有效 JSON") from None
    return payload


def fetch_usage(access_token, account_id, timeout=30):
    payload = _get_json(USAGE_URL, access_token, account_id, timeout)
    if not isinstance(payload, dict) or not any(
        key in payload for key in ("plan_type", "rate_limit", "additional_rate_limits")
    ):
        raise ValueError("用量接口返回了无法识别的数据")
    return payload


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _local_time(timestamp):
    if isinstance(timestamp, str):
        try:
            value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            return value.astimezone().isoformat() if value.tzinfo is not None else None
        except (ValueError, OverflowError, OSError):
            return None
    if _number(timestamp) is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).astimezone().isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def summarize_reset_credits(payload):
    if payload is None:
        return {"available_count": None, "credits": None}
    if not isinstance(payload, dict):
        raise ValueError("重置卡信息格式无效")
    count = payload.get("available_count")
    count = count if type(count) is int and count >= 0 else None
    rows = payload.get("credits")
    credits = None
    if rows is not None:
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("重置卡明细格式无效")
        credits = []
        for row in rows:
            expires_at = row.get("expires_at")
            credits.append(
                {
                    "status": (
                        row.get("status")
                        if isinstance(row.get("status"), str)
                        else None
                    ),
                    "expires_at": expires_at if isinstance(expires_at, str) else None,
                    "expires_at_local": _local_time(expires_at),
                }
            )
    return {"available_count": count, "credits": credits}


def fetch_reset_credits(access_token, account_id, timeout=30):
    payload = _get_json(RESET_CREDITS_URL, access_token, account_id, timeout)
    required = {"available_count", "credits"}
    if not isinstance(payload, dict) or not required <= payload.keys():
        raise ValueError("重置卡接口返回了无法识别的数据")
    return summarize_reset_credits(payload)


def summarize_usage(payload):
    """仅输出用量字段，避免把服务端返回的身份数据带入日志。"""
    groups = []
    sources = [("Codex", payload.get("rate_limit"))]
    if payload.get("code_review_rate_limit") is not None:
        sources.append(("Code review", payload["code_review_rate_limit"]))
    additional = payload.get("additional_rate_limits") or []
    if not isinstance(additional, list):
        raise ValueError("额外额度组格式无效")
    for item in additional:
        if not isinstance(item, dict):
            raise ValueError("额外额度组格式无效")
        sources.append(
            (
                item.get("limit_name") or item.get("metered_feature") or "额外额度",
                item.get("rate_limit"),
            )
        )
    for name, limit in sources:
        if limit is None:
            limit = {}
        if not isinstance(limit, dict):
            raise ValueError("额度组格式无效")
        windows = []
        for key in ("primary_window", "secondary_window"):
            window = limit.get(key)
            if window is None:
                continue
            if not isinstance(window, dict):
                raise ValueError("额度窗口格式无效")
            used = _number(window.get("used_percent"))
            reset_at = _number(window.get("reset_at"))
            windows.append(
                {
                    "window": key,
                    "used_percent": used,
                    "remaining_percent": (
                        None if used is None else max(0, min(100, 100 - used))
                    ),
                    "limit_window_seconds": _number(window.get("limit_window_seconds")),
                    "reset_after_seconds": _number(window.get("reset_after_seconds")),
                    "reset_at": reset_at,
                    "reset_at_local": _local_time(reset_at),
                }
            )
        groups.append(
            {
                "name": name,
                "allowed": (
                    limit.get("allowed") if type(limit.get("allowed")) is bool else None
                ),
                "limit_reached": (
                    limit.get("limit_reached")
                    if type(limit.get("limit_reached")) is bool
                    else None
                ),
                "windows": windows,
            }
        )
    return {
        "plan_type": payload.get("plan_type"),
        "limits": groups,
        "rate_limit_reset_credits": summarize_reset_credits(
            payload.get("rate_limit_reset_credits")
        ),
    }


def _format_duration(seconds):
    if _number(seconds) is None:
        return "未知"
    seconds = max(0, int(seconds))
    parts = []
    for size, unit in ((86400, "天"), (3600, "小时"), (60, "分"), (1, "秒")):
        value, seconds = divmod(seconds, size)
        if value:
            parts.append(f"{value} {unit}")
    return " ".join(parts) or "0 秒"


def _format_datetime(value):
    local = _local_time(value)
    if local is None:
        return "未知"
    return datetime.fromisoformat(local).strftime("%Y-%m-%d %H:%M:%S")


def _quota_style(remaining):
    if remaining is None:
        return "dim"
    if remaining <= 10:
        return "bold red"
    if remaining <= 25:
        return "yellow"
    return "green"


def _exhausted_windows(group):
    return [
        window
        for window in group["windows"]
        if window["remaining_percent"] is not None and window["remaining_percent"] <= 0
    ]


def _quota_status(group):
    exhausted = _exhausted_windows(group)
    if exhausted:
        durations = {window["limit_window_seconds"] for window in exhausted}
        if 604800 in durations and 18000 in durations:
            reason = "5 小时及本周额度用尽"
        elif 604800 in durations:
            reason = "本周额度用尽"
        elif 18000 in durations:
            reason = "5 小时额度用尽"
        else:
            reason = "额度已耗尽"
        return f"暂不可用 · {reason}", "bold red"
    if group["allowed"] is False or group["limit_reached"] is True:
        return "暂不可用 · 服务端限制", "bold red"
    remaining = [window["remaining_percent"] for window in group["windows"]]
    if not remaining or any(value is None for value in remaining):
        return "状态待确认 · 额度未知", "yellow"
    if group["allowed"] is not True:
        return "状态待确认 · 接口未明确允许", "yellow"
    return "当前可用", "bold green"


def _recovery_hint(group):
    exhausted = _exhausted_windows(group)
    if not exhausted:
        return None
    waits = [window["reset_after_seconds"] for window in exhausted]
    if any(wait is None for wait in waits):
        return "恢复时间未知"
    wait = max(waits)
    if wait <= 0:
        return "重置时间已到，等待额度刷新"
    return f"预计 {_format_duration(wait)}后恢复"


def print_usage(results, console=None):
    from rich import box
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    console = console or Console()
    table = Table(
        title="Codex 用量汇总（本地时间）",
        title_justify="left",
        box=box.SIMPLE,
        expand=True,
        padding=(0, 1),
        header_style="bold cyan",
    )
    for heading, ratio in (
        ("账号 / 套餐 / 查询时间", 2),
        ("当前状态 / 窗口余量", 4),
        ("恢复 / 重置时间", 4),
        ("重置卡 / 过期时间", 3),
    ):
        table.add_column(heading, ratio=ratio, overflow="fold")
    statuses = {"available": "可用", "redeemed": "已使用", "expired": "已过期"}
    for index, result in enumerate(results):
        account = Text(str(result["account"]), style="bold cyan")
        account.append(f"\n{result.get('plan_type') or '未知套餐'}", style="default")
        account.append(f"\n{_format_datetime(result['updated_at'])}", style="dim")
        quota, resets, cards = Text(), Text(), Text()
        if "error" in result:
            quota.append(f"查询失败：{result['error']}", style="bold red")
        else:
            for group_index, group in enumerate(result["limits"]):
                if group_index:
                    quota.append("\n")
                status, style = _quota_status(group)
                prefix = f"{group['name']} · " if len(result["limits"]) > 1 else ""
                quota.append(
                    f"{prefix}{status}\n",
                    style=style,
                )
                if _exhausted_windows(group) and group["allowed"] is True:
                    quota.append("接口状态与额度不一致\n", style="yellow")
                recovery = _recovery_hint(group)
                if recovery:
                    if resets:
                        resets.append("\n")
                    resets.append(f"{prefix}{recovery}", style="bold yellow")
                if not group["windows"]:
                    quota.append("服务端未提供额度窗口", style="dim")
                for window_index, window in enumerate(group["windows"]):
                    if window_index:
                        quota.append("\n")
                    duration = window["limit_window_seconds"]
                    label = {18000: "5 小时窗口", 604800: "每周窗口"}.get(duration)
                    if label is None:
                        label = (
                            "时长未知"
                            if duration is None
                            else _format_duration(duration) + "窗口"
                        )
                    quota.append(f"{label}：")
                    used, remaining = (
                        window["used_percent"],
                        window["remaining_percent"],
                    )
                    if used is None:
                        quota.append("用量未知", style="dim")
                    else:
                        window_status = "不可用" if remaining <= 0 else "有余量"
                        separator = " · " if console.width >= 120 else "\n"
                        quota.append(
                            f"{window_status}{separator}", style=_quota_style(remaining)
                        )
                        quota.append(
                            f"剩余 {remaining:g}%", style=_quota_style(remaining)
                        )
                    if resets:
                        resets.append("\n")
                    reset_label = (
                        f"{group['name']} · {label}"
                        if len(result["limits"]) > 1
                        else label
                    )
                    resets.append(f"{reset_label} · ", style="dim")
                    resets.append(_format_datetime(window["reset_at_local"]) + "\n")
                    resets.append(
                        _format_duration(window["reset_after_seconds"]), style="cyan"
                    )
            reset_credits = result["rate_limit_reset_credits"]
            count = reset_credits["available_count"]
            cards.append(
                f"可用 {str(count) + ' 张' if count is not None else '张数未知'}",
                style="bold green" if count else "yellow",
            )
            if "reset_credits_error" in result:
                cards.append(
                    f"\n明细查询失败：{result['reset_credits_error']}", style="yellow"
                )
            credits = reset_credits["credits"]
            if credits is None:
                cards.append("\n明细和过期时间未知", style="dim")
            elif not credits:
                cards.append("\n无卡片明细", style="dim")
            else:
                for card_index, credit in enumerate(credits, 1):
                    status = credit["status"]
                    style = "green" if status == "available" else "yellow"
                    if status == "expired":
                        style = "red"
                    cards.append(
                        f"\n第 {card_index} 张 · {statuses.get(status, status or '未知')}",
                        style=style,
                    )
                    cards.append("\n" + _format_datetime(credit["expires_at_local"]))
            if credits is not None and count is not None and len(credits) < count:
                cards.append(
                    f"\n仅返回 {len(credits)} 张明细，以 {count} 张为准", style="yellow"
                )
        table.add_row(
            account, quota, resets, cards, end_section=index < len(results) - 1
        )
    console.print(table)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--env", type=Path, help="账号 env 文件路径")
    action.add_argument(
        "--encode", action="store_true", help="隐藏输入，输出 Base64 倒序值"
    )
    action.add_argument(
        "--decode", action="store_true", help="隐藏输入，还原 base64rev: 值"
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 数组输出")
    parser.add_argument(
        "--timeout", type=float, default=30, help="每个账号请求超时秒数，默认 30"
    )
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout 必须为大于 0 的有限数值")
    try:
        if args.encode or args.decode:
            value = getpass("请输入内容（输入隐藏）：")
            print(encode_token(value) if args.encode else decode_token(value))
            return 0
        accounts = load_accounts(args.env)
    except OSError:
        print("错误：无法读取指定 env 文件，请检查路径和权限", file=sys.stderr)
        return 2
    except UnicodeError:
        print("错误：env 文件必须使用 UTF-8 编码", file=sys.stderr)
        return 2
    except (ValueError, EOFError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    results = []
    for name, pair in accounts.items():
        result = {"account": name or "(默认)"}
        try:
            result.update(summarize_usage(fetch_usage(**pair, timeout=args.timeout)))
        except ValueError as exc:
            result["error"] = str(exc)
        else:
            try:
                credits = fetch_reset_credits(**pair, timeout=args.timeout)
                if credits["available_count"] is None:
                    credits["available_count"] = result["rate_limit_reset_credits"][
                        "available_count"
                    ]
                result["rate_limit_reset_credits"] = credits
            except ValueError as exc:
                result["reset_credits_error"] = str(exc)
        result["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        results.append(result)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print_usage(results)
    return (
        1
        if any(
            "error" in result or "reset_credits_error" in result for result in results
        )
        else 0
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
