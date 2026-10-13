import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sd_spider_utils import codex_detection as detection


@unittest.skipUnless(importlib.util.find_spec("numpy"), "requires model-check extra")
class CodexDetectionTests(unittest.TestCase):
    def test_three_probes_use_bundled_bank_and_keep_only_summary(self):
        response = {
            "text": ",".join(str(value) for value in range(1, 334)),
            "input_tokens": 100,
            "output_tokens": 200,
            "access_token": "private-token",
            "account_id": "private-account",
        }
        with patch(
            "sd_spider_utils._codex_probe.request_probe_async",
            new_callable=AsyncMock,
            return_value=response,
        ) as probe:
            result = asyncio.run(
                detection.detect_model("private-token", "private-account", 17)
            )
        self.assertEqual(probe.call_count, 3)
        self.assertEqual(len({call.args[0] for call in probe.call_args_list}), 3)
        for call in probe.call_args_list:
            self.assertEqual(call.args[1:], ("private-token", "private-account"))
            self.assertEqual(call.kwargs, {"timeout": 17})
        self.assertEqual(result["model"], "gpt-6-astra")
        self.assertEqual(result["reasoning_effort"], "ultra")
        self.assertEqual(result["transport"], "codex-app-server")
        self.assertEqual(result["valid_outputs"], 3)
        self.assertEqual(result["input_tokens"], 300)
        self.assertEqual(result["output_tokens"], 600)
        self.assertTrue(detection._valid_record(result))
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("text", result)

    def test_short_answer_or_probe_failure_stops_without_retry(self):
        for response in ({"text": "1, 2, 3"}, ValueError("Codex 请求失败")):
            with self.subTest(response=response):
                kwargs = (
                    {"side_effect": response}
                    if isinstance(response, Exception)
                    else {"return_value": response}
                )
                with (
                    patch(
                        "sd_spider_utils._codex_probe.request_probe_async",
                        new_callable=AsyncMock,
                        **kwargs,
                    ) as probe,
                    patch(
                        "sd_spider_utils._modeltrace.analyze_global_outputs"
                    ) as score,
                ):
                    with self.assertRaises(ValueError):
                        asyncio.run(
                            detection.detect_model("private-token", "private-account")
                        )
                self.assertGreaterEqual(probe.await_count, 1)
                self.assertLessEqual(probe.await_count, 3)
                score.assert_not_called()

    def test_ranking_labels_do_not_claim_identity_or_degradation(self):
        response = {"text": ",".join(["137"] * 333), "input_tokens": 100}
        for winner, status in (
            ("gpt-6-astra", "target_first"),
            ("other-model", "other_first"),
        ):
            scored = {
                "prediction": winner,
                "probability": 0.8,
                "used_outputs": 3,
                "results": [{"model": "gpt-6-astra", "probability": 0.2}],
            }
            with self.subTest(winner=winner):
                with (
                    patch(
                        "sd_spider_utils._codex_probe.request_probe_async",
                        new_callable=AsyncMock,
                        return_value=response,
                    ),
                    patch(
                        "sd_spider_utils._modeltrace.analyze_global_outputs",
                        return_value=scored,
                    ),
                ):
                    result = asyncio.run(
                        detection.detect_model("private-token", "private-account")
                    )
                self.assertEqual(result["status"], status)
                self.assertIn("最像", detection.STATUS_LABELS[status])
                self.assertIn("不证明模型身份", result["warning"])
                self.assertIn("ultra", result["warning"])
                self.assertIn("能力下降", result["warning"])
                self.assertEqual(result["target_probability"], 0.2)
                self.assertIsNone(result["output_tokens"])

    def test_probes_overlap_and_keep_challenge_pairing_when_completed_out_of_order(
        self,
    ):
        challenges = [
            {"prompt": f"challenge-{index}", "expected_count": count}
            for index, count in enumerate((100, 200, 300))
        ]
        answers = [
            ",".join([str(index + 1)] * challenge["expected_count"])
            for index, challenge in enumerate(challenges)
        ]
        scored = {
            "prediction": detection.MODEL,
            "probability": 0.8,
            "used_outputs": 3,
            "results": [{"model": detection.MODEL, "probability": 0.8}],
        }

        async def scenario():
            all_started = asyncio.Event()
            releases = [asyncio.Event() for _ in challenges]
            completed = [asyncio.Event() for _ in challenges]
            started = []

            async def response(prompt, access_token, account_id, timeout):
                index = next(
                    i
                    for i, challenge in enumerate(challenges)
                    if challenge["prompt"] == prompt
                )
                started.append(index)
                if len(started) == 3:
                    all_started.set()
                await releases[index].wait()
                completed[index].set()
                return {"text": answers[index], "input_tokens": index + 1}

            with (
                patch(
                    "sd_spider_utils._codex_probe.request_probe_async",
                    new=AsyncMock(side_effect=response),
                ) as probe,
                patch(
                    "sd_spider_utils._modeltrace.generate_challenges",
                    return_value=challenges,
                ),
                patch(
                    "sd_spider_utils._modeltrace.analyze_global_outputs",
                    return_value=scored,
                ) as score,
            ):
                task = asyncio.create_task(
                    detection.detect_model("private-token", "private-account")
                )
                try:
                    await asyncio.wait_for(all_started.wait(), timeout=5)
                    self.assertFalse(task.done())
                    for index in (2, 1, 0):
                        releases[index].set()
                        await asyncio.wait_for(completed[index].wait(), timeout=5)
                    result = await asyncio.wait_for(task, timeout=5)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            self.assertEqual(probe.await_count, 3)
            self.assertEqual(result["input_tokens"], 6)
            self.assertEqual(
                score.call_args.args[0],
                [
                    {"text": answer, "expected_count": challenge["expected_count"]}
                    for answer, challenge in zip(answers, challenges)
                ],
            )

        asyncio.run(scenario())

    def test_failed_probe_cancels_and_awaits_siblings_without_scoring(self):
        async def scenario(failure):
            all_started = asyncio.Event()
            never = asyncio.Event()
            cleanup_started = asyncio.Event()
            finish_cleanup = asyncio.Event()
            started, cancelled = [], []

            async def response(prompt, access_token, account_id, timeout):
                index = len(started)
                started.append(prompt)
                if len(started) == 3:
                    all_started.set()
                await all_started.wait()
                if index == 0:
                    if isinstance(failure, Exception):
                        raise failure
                    return failure
                try:
                    await never.wait()
                finally:
                    cancelled.append(index)
                    if len(cancelled) == 2:
                        cleanup_started.set()
                    await finish_cleanup.wait()

            with (
                patch(
                    "sd_spider_utils._codex_probe.request_probe_async",
                    new=AsyncMock(side_effect=response),
                ) as probe,
                patch("sd_spider_utils._modeltrace.analyze_global_outputs") as score,
            ):
                task = asyncio.create_task(
                    detection.detect_model("private-token", "private-account")
                )
                try:
                    await asyncio.wait_for(cleanup_started.wait(), timeout=5)
                    self.assertFalse(task.done())
                finally:
                    finish_cleanup.set()
                    with self.assertRaises(ValueError):
                        await asyncio.wait_for(task, timeout=5)
                self.assertCountEqual(cancelled, [1, 2])
                self.assertEqual(probe.await_count, 3)
                score.assert_not_called()

        for failure in ({"text": "1, 2, 3"}, ValueError("Codex 请求失败")):
            with self.subTest(failure=failure):
                asyncio.run(scenario(failure))


class CodexDetectionCacheTests(unittest.TestCase):
    def test_cache_scopes_accounts_and_preserves_env(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "accounts.env"
            content = "CODEX_ACCESS_TOKEN=private-token\n"
            env.write_text(content, encoding="utf-8")
            first = detection.cache_key("private-account-one")
            second = detection.cache_key("private-account-two")
            records = {
                first: detection.check_record("error", error="检测失败"),
                second: detection.check_record("error", error="已停止检测"),
            }
            detection.save_checks(env, records)
            self.assertEqual(detection.load_checks(env), records)
            self.assertNotEqual(first, second)
            self.assertEqual(detection.cache_key("private-account-one"), first)
            self.assertEqual(env.read_text(encoding="utf-8"), content)
            cache = detection.cache_path(env)
            self.assertNotIn("private", cache.read_text(encoding="utf-8"))
            self.assertEqual(cache.stat().st_mode & 0o777, 0o600)

    def test_missing_corrupt_or_stale_cache_is_not_displayed(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "accounts.env"
            self.assertEqual(detection.load_checks(env), {})
            cache = detection.cache_path(env)
            for content in ("{broken", "[]"):
                cache.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "缓存"):
                    detection.load_checks(env)
            record = detection.check_record("error", error="检测失败")
            for changed in (
                {"bank_revision": "old-bank"},
                {"reasoning_effort": "low"},
                {"model": "other-model"},
                {"checked_at": "2026-10-13T12:00:00"},
                {"status": "unknown"},
                {"status": []},
                {"status": {}},
            ):
                cache.write_text(
                    json.dumps({detection.cache_key("account"): {**record, **changed}}),
                    encoding="utf-8",
                )
                with self.subTest(changed=changed):
                    self.assertEqual(detection.load_checks(env), {})
            for probability in (10**400, float("inf"), float("nan")):
                invalid = detection.check_record(
                    "target_first",
                    prediction=detection.MODEL,
                    valid_outputs=3,
                    probability=probability,
                    target_probability=0.5,
                )
                cache.write_text(
                    json.dumps({detection.cache_key("account"): invalid}),
                    encoding="utf-8",
                )
                with self.subTest(probability=probability):
                    self.assertEqual(detection.load_checks(env), {})
            with patch.object(Path, "read_text", side_effect=PermissionError("secret")):
                with self.assertRaises(ValueError) as raised:
                    detection.load_checks(env)
            self.assertNotIn("secret", str(raised.exception))

    def test_cache_ignores_unknown_fields_on_read_and_write(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "accounts.env"
            key = detection.cache_key("private-account")
            record = detection.check_record("error", error="检测失败")
            untrusted = {
                key: {
                    **record,
                    "access_token": "private-token",
                    "account_id": "private-account",
                    "raw_output": "private-response",
                }
            }
            cache = detection.cache_path(env)
            cache.write_text(json.dumps(untrusted), encoding="utf-8")
            self.assertEqual(detection.load_checks(env), {key: record})
            detection.save_checks(env, untrusted)
            self.assertEqual(detection.load_checks(env), {key: record})
            self.assertNotIn("private", cache.read_text(encoding="utf-8"))

    def test_failed_atomic_write_preserves_previous_cache_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / "accounts.env"
            cache = detection.cache_path(env)
            cache.write_text("{}\n", encoding="utf-8")
            record = detection.check_record("error", error="检测失败")
            with patch.object(detection.os, "replace", side_effect=OSError("secret")):
                with self.assertRaisesRegex(ValueError, "仍会显示") as raised:
                    detection.save_checks(env, {detection.cache_key("account"): record})
            self.assertNotIn("secret", str(raised.exception))
            self.assertEqual(cache.read_text(encoding="utf-8"), "{}\n")
            self.assertEqual(list(Path(directory).iterdir()), [cache])

    def test_quota_import_does_not_load_optional_detector_dependencies(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import sd_spider_utils.codex_usage; "
                "import sd_spider_utils.codex_detection; "
                "assert 'numpy' not in sys.modules; "
                "assert 'sd_spider_utils._modeltrace' not in sys.modules",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
