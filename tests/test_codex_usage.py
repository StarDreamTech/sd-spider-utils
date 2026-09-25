import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from rich.console import Console

from sd_spider_utils import codex_usage as usage


class CodexUsageTests(unittest.TestCase):
    def test_env_pairs_and_invalid_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "accounts.env"
            env.write_text(
                "# credentials\nexport CODEX_ACCESS_TOKEN='secret=token' # comment\n"
                'CODEX_ACCOUNT_ID="account-one"\n'
                f"CODEX_WORK_ACCESS_TOKEN={usage.encode_token('second-token')}\n"
                "CODEX_WORK_ACCOUNT_ID=account-two # comment\nOTHER=value\n",
                encoding="utf-8-sig",
            )
            self.assertEqual(
                usage.load_accounts(env),
                {
                    None: {"access_token": "secret=token", "account_id": "account-one"},
                    "WORK": {
                        "access_token": "second-token",
                        "account_id": "account-two",
                    },
                },
            )
            for content in (
                "CODEX_ACCESS_TOKEN=secret",
                "CODEX_ACCOUNT_ID=account",
                "CODEX_ACCESS_TOKEN=\nCODEX_ACCOUNT_ID=account",
                "CODEX_ACCESS_TOKEN=secret\nCODEX_ACCESS_TOKEN=other",
                "CODEX_ACCESS_TOKEN='secret",
                "CODEX_ACCESS_TOKEN=base64rev:!!!",
                "CODEX_ACCESS_TOKEN=" + usage.encode_token("secret\r\nInjected: value"),
                "CODEX_ACCESS_TOKEN=secret token",
                "CODEX_ACCESS_TOKEN=令牌",
                "source other.env",
                "OTHER=value",
            ):
                with self.subTest(content=content):
                    env.write_text(content, encoding="utf-8")
                    with self.assertRaises(ValueError) as raised:
                        usage.load_accounts(env)
                    self.assertNotIn("secret", str(raised.exception))
            self.assertEqual(
                usage.decode_token(usage.encode_token("令牌=abc")), "令牌=abc"
            )

    def test_env_account_names_can_follow_field_names(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "accounts.env"
            content = (
                "CODEX_ACCESS_TOKEN_cpython666=first-token\n"
                "CODEX_ACCOUNT_ID_cpython666=first-id\n"
                f"CODEX_ACCESS_TOKEN_20x={usage.encode_token('second-token')}\n"
                "CODEX_ACCOUNT_ID_20x=second-id\n"
                "CODEX_WORK_ACCESS_TOKEN=work-token\n"
                "CODEX_WORK_ACCOUNT_ID=work-id\n"
            )
            env.write_text(content, encoding="utf-8")
            self.assertEqual(
                usage.load_accounts(env),
                {
                    "cpython666": {
                        "access_token": "first-token",
                        "account_id": "first-id",
                    },
                    "20x": {"access_token": "second-token", "account_id": "second-id"},
                    "WORK": {"access_token": "work-token", "account_id": "work-id"},
                },
            )
            for duplicate in (
                "CODEX_cpython666_ACCESS_TOKEN=other-token\n",
                "CODEX_cpython666_ACCOUNT_ID=other-id\n",
            ):
                env.write_text(content + duplicate, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "重复"):
                    usage.load_accounts(env)
            env.write_text(
                "CODEX_ACCESS_TOKEN_appleid=账号2令牌\nCODEX_ACCOUNT_ID_appleid=账号2ID\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "第 1 行"):
                usage.load_accounts(env)

    def test_response_mapping_and_text(self):
        result = usage.summarize_usage(
            {
                "plan_type": "plus",
                "rate_limit": {
                    "allowed": False,
                    "limit_reached": True,
                    "primary_window": {
                        "used_percent": 35,
                        "limit_window_seconds": 18000,
                        "reset_at": 2000000000,
                        "reset_after_seconds": 1800,
                    },
                    "secondary_window": {"used_percent": 120},
                },
                "additional_rate_limits": [
                    {"limit_name": "Extra", "rate_limit": {"primary_window": {}}}
                ],
                "access_token": "must-not-be-printed",
            }
        )
        primary, secondary = result["limits"][0]["windows"]
        self.assertEqual(primary["remaining_percent"], 65)
        self.assertEqual(primary["limit_window_seconds"], 18000)
        self.assertIsNotNone(primary["reset_at_local"])
        self.assertEqual(secondary["remaining_percent"], 0)
        self.assertIsNone(secondary["reset_at_local"])
        self.assertIsNone(result["limits"][1]["windows"][0]["remaining_percent"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            usage.print_usage(
                [dict(result, account="WORK", updated_at="now")],
                Console(width=140),
            )
        for expected in (
            "剩余 65%",
            "5 小时窗口",
            "重置时间",
            "额度已耗尽",
            "用量未知",
        ):
            self.assertIn(expected, output.getvalue())
        self.assertNotIn("must-not-be-printed", json.dumps(result))
        self.assertEqual(
            usage.summarize_usage({"rate_limit": None})["limits"][0]["windows"], []
        )
        with self.assertRaises(ValueError):
            usage.summarize_usage({"rate_limit": "invalid"})

    def test_http_headers_and_safe_errors(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(b'{"plan_type":"plus"}')
        with patch.object(usage, "build_opener", return_value=opener) as factory:
            self.assertEqual(
                usage.fetch_usage("secret", "account", 12), {"plan_type": "plus"}
            )
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, usage.USAGE_URL)
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(request.get_header("Chatgpt-account-id"), "account")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 12)
        redirect_handler = factory.call_args.args[0]
        self.assertIsNone(
            redirect_handler.redirect_request(
                request, None, 302, "", {}, "https://example.com"
            )
        )
        for error in (
            HTTPError(usage.USAGE_URL, 401, "secret", {}, None),
            HTTPError(usage.USAGE_URL, 403, "secret", {}, None),
            HTTPError(usage.USAGE_URL, 429, "secret", {}, None),
            URLError("secret"),
            TimeoutError("secret"),
        ):
            opener.open.side_effect = error
            with patch.object(usage, "build_opener", return_value=opener):
                with self.assertRaises(ValueError) as raised:
                    usage.fetch_usage("secret", "account")
            self.assertNotIn("secret", str(raised.exception))
        opener.open.side_effect = None
        for body in (b"<html>secret</html>", b"[]", b'{"error":"secret"}'):
            opener.open.return_value = io.BytesIO(body)
            with patch.object(usage, "build_opener", return_value=opener):
                with self.assertRaises(ValueError) as raised:
                    usage.fetch_usage("secret", "account")
            self.assertNotIn("secret", str(raised.exception))

    def test_cli_continues_after_one_account_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "accounts.env"
            env.write_text(
                "CODEX_ACCESS_TOKEN=secret\nCODEX_ACCOUNT_ID=private-id\n"
                "CODEX_WORK_ACCESS_TOKEN=second-secret\nCODEX_WORK_ACCOUNT_ID=second-id\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            responses = [ValueError("HTTP 401：登录令牌失效"), {"plan_type": "plus"}]
            with (
                patch.object(usage, "fetch_usage", side_effect=responses) as fetch,
                patch.object(
                    usage,
                    "fetch_reset_credits",
                    return_value={"available_count": 0, "credits": []},
                ),
            ):
                with contextlib.redirect_stdout(output):
                    status = usage.main(["--env", str(env), "--json"])
            self.assertEqual(status, 1)
            self.assertEqual(fetch.call_count, 2)
            results = json.loads(output.getvalue())
            self.assertIn("error", results[0])
            self.assertEqual(results[1]["plan_type"], "plus")
            self.assertIn("updated_at", results[1])
            self.assertNotIn("secret", output.getvalue())
            self.assertNotIn("private-id", output.getvalue())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    usage.main(["--env", str(env.with_name("missing.env"))]), 2
                )
                for timeout in ("0", "-1", "nan", "inf"):
                    with self.assertRaises(SystemExit) as raised:
                        usage.main(["--env", str(env), "--timeout", timeout])
                    self.assertEqual(raised.exception.code, 2)

    def test_reset_cards_are_read_only_and_keep_authoritative_count(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "accounts.env"
            env.write_text(
                "CODEX_ACCESS_TOKEN=secret\nCODEX_ACCOUNT_ID=account\n",
                encoding="utf-8",
            )
            opener = Mock()
            opener.open.side_effect = [
                io.BytesIO(
                    b'{"plan_type":"plus","rate_limit_reset_credits":{"available_count":4}}'
                ),
                io.BytesIO(
                    json.dumps(
                        {
                            "available_count": 3,
                            "credits": [
                                {
                                    "status": "available",
                                    "expires_at": "2026-10-17T00:00:00Z",
                                    "profile_user_id": "private-profile",
                                },
                                {"status": "available", "expires_at": None},
                            ],
                        }
                    ).encode()
                ),
            ]
            output = io.StringIO()
            with (
                patch.object(usage, "build_opener", return_value=opener),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(usage.main(["--env", str(env), "--json"]), 0)
            requests = [call.args[0] for call in opener.open.call_args_list]
            self.assertEqual(
                [request.full_url for request in requests],
                [usage.USAGE_URL, usage.RESET_CREDITS_URL],
            )
            self.assertTrue(
                all(
                    request.get_method() == "GET" and request.data is None
                    for request in requests
                )
            )
            self.assertTrue(
                all(
                    request.get_header("Authorization") == "Bearer secret"
                    for request in requests
                )
            )
            results = json.loads(output.getvalue())
            cards = results[0]["rate_limit_reset_credits"]
            self.assertEqual(cards["available_count"], 3)  # 不用明细条数代替总张数。
            self.assertEqual(
                cards["credits"][0]["expires_at_local"],
                usage._local_time("2026-10-17T00:00:00Z"),
            )
            self.assertIsNotNone(cards["credits"][0]["expires_at_local"])
            self.assertIsNone(cards["credits"][1]["expires_at_local"])
            self.assertNotIn("private-profile", output.getvalue())
            text = io.StringIO()
            with contextlib.redirect_stdout(text):
                usage.print_usage(results, Console(width=140))
            self.assertIn("可用 3 张", text.getvalue())
            self.assertIn("仅返回 2 张明细", text.getvalue())
            self.assertIn("过期时间", text.getvalue())
            self.assertIn("未知", text.getvalue())
            with patch.object(usage, "build_opener") as factory:
                with self.assertRaises(ValueError):
                    usage._get_json(
                        usage.RESET_CREDITS_URL + "/consume", "secret", "account", 30
                    )
                factory.assert_not_called()

    def test_reset_card_details_failure_preserves_usage_and_count(self):
        accounts = {None: {"access_token": "secret", "account_id": "account"}}
        for error in (
            HTTPError(usage.RESET_CREDITS_URL, 403, "secret", {}, None),
            TimeoutError("secret"),
        ):
            opener = Mock()
            opener.open.side_effect = [
                io.BytesIO(
                    b'{"plan_type":"plus","rate_limit_reset_credits":{"available_count":2}}'
                ),
                error,
            ]
            output = io.StringIO()
            with (
                patch.object(usage, "load_accounts", return_value=accounts),
                patch.object(usage, "build_opener", return_value=opener),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(usage.main(["--env", "unused.env", "--json"]), 1)
            result = json.loads(output.getvalue())[0]
            self.assertEqual(result["plan_type"], "plus")
            self.assertEqual(
                result["rate_limit_reset_credits"],
                {"available_count": 2, "credits": None},
            )
            self.assertIn("reset_credits_error", result)
            self.assertNotIn("error", result)
            self.assertNotIn("secret", output.getvalue())

    def test_reset_card_unknown_zero_and_invalid_expiry(self):
        self.assertEqual(
            usage.summarize_reset_credits(None),
            {"available_count": None, "credits": None},
        )
        self.assertEqual(
            usage.summarize_reset_credits({"available_count": 0, "credits": []}),
            {"available_count": 0, "credits": []},
        )
        self.assertEqual(
            usage.summarize_reset_credits({"available_count": 3})["credits"], None
        )
        for timestamp in (None, "invalid", "2026-10-17T00:00:00"):
            card = usage.summarize_reset_credits(
                {"credits": [{"expires_at": timestamp}]}
            )["credits"][0]
            self.assertIsNone(card["expires_at_local"])
        with self.assertRaises(ValueError):
            usage.summarize_reset_credits({"credits": "invalid"})

    def test_exhausted_window_takes_priority_over_server_allowed_flag(self):
        for percentages, allowed, reached, expected in (
            ([100], True, False, "暂不可用 · 本周额度用尽"),
            ([79, 100], True, False, "暂不可用 · 本周额度用尽"),
            ([120], False, True, "暂不可用 · 本周额度用尽"),
            ([77], True, False, "当前可用"),
            ([77], False, False, "暂不可用 · 服务端限制"),
            ([77], True, True, "暂不可用 · 服务端限制"),
            ([None], True, False, "状态待确认 · 额度未知"),
            ([], True, False, "状态待确认 · 额度未知"),
            ([77], None, False, "状态待确认 · 接口未明确允许"),
        ):
            windows = dict(
                zip(
                    ("primary_window", "secondary_window"),
                    (
                        {"used_percent": value, "limit_window_seconds": 604800}
                        for value in percentages
                    ),
                )
            )
            result = usage.summarize_usage(
                {
                    "plan_type": "plus",
                    "rate_limit": dict(windows, allowed=allowed, limit_reached=reached),
                }
            )
            group = result["limits"][0]
            self.assertEqual(usage._quota_status(group)[0], expected)
            before = json.dumps(result)
            output = io.StringIO()
            usage.print_usage(
                [dict(result, account="test", updated_at="2026-09-23T14:31:14+08:00")],
                Console(file=output, width=140, color_system=None),
            )
            self.assertIn(expected, output.getvalue())
            if "额度用尽" in expected and allowed:
                self.assertIn("接口状态与额度不一致", output.getvalue())
                self.assertNotIn("当前可用", output.getvalue())
            self.assertEqual(json.dumps(result), before)
            self.assertIs(group["allowed"], allowed)
            self.assertIs(group["limit_reached"], reached)

    def test_window_reason_and_recovery_time(self):
        def group(short_used, weekly_used, short_wait=3600, weekly_wait=86400):
            return usage.summarize_usage(
                {
                    "rate_limit": {
                        "allowed": True,
                        "limit_reached": False,
                        "primary_window": {
                            "used_percent": short_used,
                            "limit_window_seconds": 18000,
                            "reset_after_seconds": short_wait,
                        },
                        "secondary_window": {
                            "used_percent": weekly_used,
                            "limit_window_seconds": 604800,
                            "reset_after_seconds": weekly_wait,
                        },
                    }
                }
            )["limits"][0]

        for short, weekly, reason, recovery in (
            (100, 79, "暂不可用 · 5 小时额度用尽", "预计 1 小时后恢复"),
            (0, 100, "暂不可用 · 本周额度用尽", "预计 1 天后恢复"),
            (100, 100, "暂不可用 · 5 小时及本周额度用尽", "预计 1 天后恢复"),
            (0, 79, "当前可用", None),
        ):
            current = group(short, weekly)
            self.assertEqual(usage._quota_status(current)[0], reason)
            self.assertEqual(usage._recovery_hint(current), recovery)
        self.assertEqual(
            usage._recovery_hint(group(100, 100, short_wait=172800)), "预计 2 天后恢复"
        )
        self.assertEqual(
            usage._recovery_hint(group(100, 100, short_wait=None)), "恢复时间未知"
        )
        self.assertEqual(
            usage._recovery_hint(group(100, 79, short_wait=0)),
            "重置时间已到，等待额度刷新",
        )
        self.assertEqual(
            usage._recovery_hint(group(100, 79, short_wait=-1)),
            "重置时间已到，等待额度刷新",
        )

    def test_readable_duration_and_colored_output(self):
        for seconds, expected in (
            (177210, "2 天 1 小时 13 分 30 秒"),
            (126087, "1 天 11 小时 1 分 27 秒"),
            (18000, "5 小时"),
            (59, "59 秒"),
            (0, "0 秒"),
            (-1, "0 秒"),
            (None, "未知"),
            (float("nan"), "未知"),
        ):
            self.assertEqual(usage._format_duration(seconds), expected)
        formatted = usage._format_datetime("2026-10-23T04:42:26.640959+08:00")
        self.assertRegex(formatted, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertEqual(usage._format_datetime("invalid"), "未知")
        for remaining, style in (
            (100, "green"),
            (26, "green"),
            (25, "yellow"),
            (11, "yellow"),
            (10, "bold red"),
            (0, "bold red"),
            (None, "dim"),
        ):
            self.assertEqual(usage._quota_style(remaining), style)
        results = []
        for used in (0, 75, 100):
            result = usage.summarize_usage(
                {
                    "plan_type": "plus",
                    "rate_limit": {
                        "allowed": True,
                        "limit_reached": False,
                        "primary_window": {
                            "used_percent": used,
                            "limit_window_seconds": 604800,
                            "reset_after_seconds": 177210,
                            "reset_at": 2000000000,
                        },
                    },
                }
            )
            results.append(
                dict(
                    result,
                    account=f"demo-{used}",
                    updated_at="2026-09-23T13:07:34+08:00",
                )
            )
        # 宽窄终端都不截断时间数值；重定向不输出 ANSI 控制码。
        console = Mock()
        console.width = 140
        usage.print_usage(results, console)
        console.print.assert_called_once()
        self.assertEqual(len(console.print.call_args.args[0].rows), 3)
        for width in (60, 100):
            output = io.StringIO()
            usage.print_usage(
                results, Console(file=output, width=width, color_system=None)
            )
            normalized = " ".join(output.getvalue().replace("│", " ").split())
            for expected in ("每周窗口", "2 天", "30 秒", "剩余 0%", "剩余 100%"):
                self.assertIn(expected, normalized)
            self.assertNotIn("…", output.getvalue())
            if width == 100:
                self.assertIn("2 天 1 小时 13 分 30 秒", normalized)
            self.assertNotIn("177210", output.getvalue())
            self.assertNotIn("\x1b", output.getvalue())
            self.assertNotIn("仅查询，不使用", output.getvalue())
            self.assertEqual(output.getvalue().count("Codex 用量汇总"), 1)
        colored = io.StringIO()
        usage.print_usage(
            results,
            Console(
                file=colored,
                width=100,
                force_terminal=True,
                color_system="standard",
                no_color=False,
            ),
        )
        for code in ("\x1b[32m", "\x1b[33m", "\x1b[1;31m"):
            self.assertIn(code, colored.getvalue())


if __name__ == "__main__":
    unittest.main()
