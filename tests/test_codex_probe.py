import asyncio
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sd_spider_utils import _codex_probe as probe


def _transcript(*notifications, model=probe.MODEL, effort=probe.REASONING_EFFORT):
    replies = [
        {"id": 1, "result": {}},
        {
            "id": 2,
            "result": {
                "data": [
                    {
                        "model": probe.MODEL,
                        "supportedReasoningEfforts": [
                            {"reasoningEffort": probe.REASONING_EFFORT}
                        ],
                    }
                ]
            },
        },
        {"id": 3, "result": {"type": "chatgptAuthTokens"}},
        {
            "id": 4,
            "result": {
                "thread": {"id": "probe-thread"},
                "model": model,
                "reasoningEffort": effort,
            },
        },
        {"id": 5, "result": {"turn": {"id": "probe-turn"}}},
    ]
    return replies + list(notifications)


def _notice(method, **params):
    return {
        "method": method,
        "params": {
            "threadId": "probe-thread",
            "turnId": "probe-turn",
            **params,
        },
    }


def _done(status="completed", text="1, 2, 3"):
    return _notice(
        "turn/completed",
        turn={
            "id": "probe-turn",
            "status": status,
            "error": None,
            "items": [
                {
                    "id": "answer",
                    "type": "agentMessage",
                    "text": text,
                    "phase": "final_answer",
                }
            ],
        },
    )


class _Input(io.BytesIO):
    async def drain(self):
        pass


class CodexProbeTests(unittest.TestCase):
    def run_probe(self, transcript, **kwargs):
        process = Mock(returncode=None)
        process.stdin = _Input()
        lines = [(json.dumps(message) + "\n").encode() for message in transcript]
        process.stdout.readline = AsyncMock(side_effect=lines + [b""])
        process.wait = AsyncMock(return_value=0)
        with (
            patch.object(probe.shutil, "which", return_value="/test/codex"),
            patch.object(
                probe.asyncio,
                "create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ) as launch,
        ):
            result = probe.request_probe(
                "numbers please", "fake-token", "fake-account", **kwargs
            )
        return result, process, launch

    def test_isolated_ultra_runtime_and_complete_final_text(self):
        transcript = _transcript(
            _notice("item/agentMessage/delta", delta="must-not-duplicate"),
            _notice(
                "item/completed",
                item={
                    "id": "answer",
                    "type": "agentMessage",
                    "phase": "final_answer",
                    "text": "1, 2, 3",
                },
            ),
            _notice(
                "thread/tokenUsage/updated",
                tokenUsage={
                    "total": {"inputTokens": 200, "outputTokens": 150},
                },
            ),
            _done(),
        )
        with patch.dict(
            probe.os.environ,
            {
                "OPENAI_API_KEY": "must-not-inherit",
                "CODEX_HOME": "/real/codex",
                "CODEX_THREAD_ID": "real-thread",
                "HTTPS_PROXY": "http://local-proxy",
            },
        ):
            result, process, launch = self.run_probe(transcript)
        self.assertEqual(result["text"], "1, 2, 3")
        self.assertEqual(result["runtime_effort"], "ultra")
        self.assertIsNone(result["reported_model"])
        self.assertEqual((result["input_tokens"], result["output_tokens"]), (200, 150))
        sent = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
        login = next(m for m in sent if m.get("method") == "account/login/start")
        self.assertEqual(
            login["params"],
            {
                "type": "chatgptAuthTokens",
                "accessToken": "fake-token",
                "chatgptAccountId": "fake-account",
            },
        )
        thread = next(m for m in sent if m.get("method") == "thread/start")["params"]
        turn = next(m for m in sent if m.get("method") == "turn/start")["params"]
        self.assertEqual((thread["model"], turn["model"]), (probe.MODEL, probe.MODEL))
        self.assertEqual(turn["effort"], "ultra")
        self.assertEqual(thread["environments"], [])
        self.assertFalse(thread["allowProviderModelFallback"])
        self.assertTrue(thread["ephemeral"])
        arguments, options = launch.call_args.args, launch.call_args.kwargs
        self.assertNotIn("fake-token", str(arguments) + str(options))
        self.assertNotIn("OPENAI_API_KEY", options["env"])
        self.assertNotIn("CODEX_THREAD_ID", options["env"])
        self.assertEqual(options["env"]["HTTPS_PROXY"], "http://local-proxy")
        self.assertEqual(options["cwd"], options["env"]["CODEX_HOME"])
        self.assertFalse(Path(options["cwd"]).exists())
        process.kill.assert_called_once()

    def test_no_partial_failed_switched_or_tool_output_is_accepted(self):
        cases = [
            _transcript(_done("failed")),
            _transcript(_done("interrupted")),
            _transcript(_notice("item/agentMessage/delta", delta="1, 2, 3")),
            _transcript(_done(text="")),
            _transcript(_done(), effort="xhigh"),
            _transcript(_done(), model="gpt-6-sol"),
            _transcript(
                _notice("item/started", item={"type": "commandExecution"}), _done()
            ),
            _transcript(
                _notice("item/started", item={"type": "collabAgentToolCall"}), _done()
            ),
            _transcript(
                {
                    "id": "server-request",
                    "method": "account/chatgptAuthTokens/refresh",
                    "params": {},
                }
            ),
            _transcript(_notice("error", error={"message": "fake-token"})),
            _transcript(_notice("model/rerouted", toModel="gpt-6-sol"), _done()),
            [{"id": 1, "error": {"message": "fake-token"}}],
        ]
        for transcript in cases:
            with (
                self.subTest(transcript=transcript),
                self.assertRaises(ValueError) as raised,
            ):
                self.run_probe(transcript)
            self.assertNotIn("fake-token", str(raised.exception))

    def test_output_bound_and_unknown_token_counts(self):
        with (
            patch.object(probe, "_MAX_OUTPUT_BYTES", 10),
            self.assertRaisesRegex(ValueError, "过大"),
        ):
            self.run_probe(_transcript(_done()))
        result, _, _ = self.run_probe(
            _transcript(
                _notice(
                    "thread/tokenUsage/updated",
                    tokenUsage={
                        "total": {"inputTokens": True, "outputTokens": -1},
                    },
                ),
                _done(),
            )
        )
        self.assertIsNone(result["input_tokens"])
        self.assertIsNone(result["output_tokens"])

    def test_invalid_inputs_and_missing_cli_do_not_launch(self):
        for kwargs in ({"timeout": 0}, {"timeout": float("nan")}):
            with self.assertRaises(ValueError):
                probe.request_probe("prompt", "fake-token", "fake-account", **kwargs)
        with (
            patch.object(probe.shutil, "which", return_value=None),
            patch.object(probe.sys, "platform", "linux"),
        ):
            with self.assertRaisesRegex(ValueError, "未找到 Codex CLI"):
                probe.request_probe("prompt", "fake-token", "fake-account")
        with self.assertRaises(ValueError) as raised:
            probe.request_probe("prompt", "fake-token\nInjected", "fake-account")
        self.assertNotIn("fake-token", str(raised.exception))

    def test_cli_discovery_prefers_path_and_falls_back_to_macos_app(self):
        with patch.object(probe.shutil, "which", return_value="/custom/codex"):
            self.assertEqual(probe._find_codex(), "/custom/codex")
        with tempfile.TemporaryDirectory() as directory:
            bundled = Path(
                directory,
                "Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
            )
            bundled.parent.mkdir(parents=True)
            bundled.write_text("placeholder", encoding="utf-8")
            with (
                patch.object(probe.shutil, "which", return_value=None),
                patch.object(probe.sys, "platform", "darwin"),
                patch.object(probe.Path, "home", return_value=Path(directory)),
                patch.object(
                    probe.os, "access", side_effect=lambda path, mode: path == bundled
                ),
            ):
                self.assertEqual(probe._find_codex(), str(bundled))
            with (
                patch.object(probe.shutil, "which", return_value=None),
                patch.object(probe.sys, "platform", "darwin"),
                patch.object(probe.os, "access", return_value=False),
                self.assertRaisesRegex(ValueError, "未找到 Codex CLI"),
            ):
                probe._find_codex()

    def test_deadline_kills_process(self):
        async def stalled():
            await asyncio.sleep(10)

        process = Mock(returncode=None)
        process.stdin = _Input()
        process.stdout.readline = stalled
        process.wait = AsyncMock(return_value=0)
        with (
            patch.object(probe.shutil, "which", return_value="/test/codex"),
            patch.object(
                probe.asyncio,
                "create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            self.assertRaisesRegex(ValueError, "超时"),
        ):
            probe.request_probe("prompt", "fake-token", "fake-account", timeout=0.01)
        process.kill.assert_called_once()

    def test_cancelled_probe_waits_for_process_and_removes_temporary_directory(self):
        async def scenario():
            reading = asyncio.Event()
            never = asyncio.Event()
            waiting_for_exit = asyncio.Event()
            exited = asyncio.Event()

            async def stalled():
                reading.set()
                await never.wait()

            async def wait_for_exit():
                waiting_for_exit.set()
                await exited.wait()
                return 0

            process = Mock(returncode=None)
            process.stdin = _Input()
            process.stdout.readline = stalled
            process.wait = AsyncMock(side_effect=wait_for_exit)
            with (
                patch.object(probe.shutil, "which", return_value="/test/codex"),
                patch.object(
                    probe.asyncio,
                    "create_subprocess_exec",
                    new=AsyncMock(return_value=process),
                ) as launch,
            ):
                task = asyncio.create_task(
                    probe.request_probe_async("prompt", "fake-token", "fake-account")
                )
                cancelled = False
                try:
                    await asyncio.wait_for(reading.wait(), timeout=5)
                    directory = Path(launch.call_args.kwargs["cwd"])
                    self.assertTrue(directory.is_dir())
                    task.cancel()
                    cancelled = True
                    await asyncio.wait_for(waiting_for_exit.wait(), timeout=5)
                    self.assertFalse(task.done())
                    self.assertTrue(directory.is_dir())
                finally:
                    exited.set()
                    if not cancelled:
                        task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
            process.kill.assert_called_once()
            process.wait.assert_awaited_once()
            self.assertFalse(directory.exists())

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
