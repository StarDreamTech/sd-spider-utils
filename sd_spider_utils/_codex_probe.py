"""Run an isolated numeric probe through the installed Codex app-server."""

import asyncio
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile


MODEL = "gpt-6-astra"
REASONING_EFFORT = "ultra"
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_MAX_LINE_BYTES = 2 * 1024 * 1024

# Use the actual Codex effort resolver: Ultra is a runtime mode, not a raw
# Responses API effort. Never substitute another model or effort here.
_CONFIG = {
    "model_reasoning_effort": REASONING_EFFORT,
    "forced_login_method": "chatgpt",
    "cli_auth_credentials_store": "file",
    "web_search": "disabled",
    "project_doc_max_bytes": 0,
    "include_environment_context": False,
    "include_apps_instructions": False,
    "include_permissions_instructions": False,
    "features.skip_host_skill_discovery": True,
    "features.shell_tool": False,
    "features.unified_exec": False,
    "features.apply_patch_freeform": False,
    "features.apps": False,
    "features.plugins": False,
    "features.plugin_hooks": False,
    "features.hooks": False,
    "features.browser_use": False,
    "features.computer_use": False,
    "features.image_generation": False,
    "features.js_repl": False,
    "features.multi_agent": False,
    "features.multi_agent_v2": False,
    "features.remote_models": False,
    "features.unbounded_connection_retries": False,
}


class _ProbeError(ValueError):
    """An error whose message contains no upstream data or credentials."""


def _find_codex():
    executable = shutil.which("codex")
    if executable:
        return executable
    if sys.platform == "darwin":
        # The desktop app adds its bundled CLI to its own PATH, not every terminal's.
        relative = (
            "ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
        )
        for directory in (Path("/Applications"), Path.home() / "Applications"):
            candidate = directory / relative
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    raise ValueError(
        "未找到 Codex CLI，请安装并确保 codex 在 PATH 中；macOS 也支持 ChatGPT 应用内置 CLI"
    )


def _process_environment(directory):
    # Preserve only process/runtime and network settings; do not inherit API keys,
    # CODEX_* overrides, an app-server address, or the current chat's identity.
    allowed = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
    }
    environment = {
        key: value for key, value in os.environ.items() if key.upper() in allowed
    }
    environment["CODEX_HOME"] = directory
    return environment


async def _conversation(process, directory, prompt, access_token, account_id):
    sequence = 0
    received = 0
    pending = []

    async def send(message):
        process.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        await process.stdin.drain()

    async def read():
        nonlocal received
        line = await process.stdout.readline()
        received += len(line)
        if received > _MAX_OUTPUT_BYTES:
            raise _ProbeError("Codex 检测输出过大，本次未采用")
        if not line:
            raise _ProbeError("Codex 提前退出或未返回完整结果")
        try:
            message = json.loads(line)
        except (ValueError, UnicodeError):
            raise _ProbeError("Codex 返回了无效的协议数据") from None
        if not isinstance(message, dict):
            raise _ProbeError("Codex 返回了无效的协议数据")
        if "method" in message and "id" in message:
            # No browser login, token refresh, approvals or client-side tools.
            await send(
                {
                    "id": message["id"],
                    "error": {
                        "code": -32601,
                        "message": "Not available for numeric probes",
                    },
                }
            )
            raise _ProbeError("Codex 请求额外授权、刷新令牌或工具，本次未采用")
        return message

    async def rpc(method, params):
        nonlocal sequence
        sequence += 1
        await send({"id": sequence, "method": method, "params": params})
        while True:
            message = await read()
            if message.get("id") == sequence:
                if "error" in message or not isinstance(message.get("result"), dict):
                    raise _ProbeError(
                        "Codex 拒绝检测配置或账号，请检查 CLI 版本与登录状态"
                    )
                return message["result"]
            pending.append(message)

    await rpc(
        "initialize",
        {
            "clientInfo": {"name": "sd_codex_probe", "version": "1"},
            "capabilities": {"experimentalApi": True, "requestAttestation": False},
        },
    )
    await send({"method": "initialized"})
    catalog = await rpc("model/list", {"includeHidden": True, "limit": 100})
    efforts = []
    for model in catalog.get("data", []):
        if model.get("model") == MODEL:
            efforts = model.get("supportedReasoningEfforts", [])
    if not any(option.get("reasoningEffort") == REASONING_EFFORT for option in efforts):
        raise _ProbeError("当前 Codex CLI 未声明支持 gpt-6-astra ultra，请更新 CLI")
    await rpc(
        "account/login/start",
        {
            "type": "chatgptAuthTokens",
            "accessToken": access_token,
            "chatgptAccountId": account_id,
        },
    )
    started = await rpc(
        "thread/start",
        {
            "model": MODEL,
            "modelProvider": "openai",
            "allowProviderModelFallback": False,
            "cwd": directory,
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "ephemeral": True,
            "environments": [],
            "baseInstructions": "",
            "developerInstructions": "Answer the numeric sampling prompt directly. Do not use tools or delegate.",
            "config": {"model_reasoning_effort": REASONING_EFFORT},
        },
    )
    configured = (started.get("model"), started.get("reasoningEffort"))
    if configured != (MODEL, REASONING_EFFORT):
        raise _ProbeError("Codex 未采用指定的 gpt-6-astra ultra，本次未采用")
    thread_id = started.get("thread", {}).get("id")
    if not isinstance(thread_id, str) or not thread_id:
        raise _ProbeError("Codex 未返回检测会话")
    pending.clear()
    turn = await rpc(
        "turn/start",
        {
            "threadId": thread_id,
            "model": MODEL,
            "effort": REASONING_EFFORT,
            "environments": [],
            "input": [{"type": "text", "text": prompt, "text_elements": []}],
        },
    )
    turn_id = turn.get("turn", {}).get("id")
    if not isinstance(turn_id, str) or not turn_id:
        raise _ProbeError("Codex 未返回检测轮次")
    messages = {}
    usage = {}
    while True:
        message = pending.pop(0) if pending else await read()
        method = message.get("method")
        params = message.get("params")
        if not isinstance(params, dict) or params.get("threadId") != thread_id:
            continue
        if params.get("turnId", turn_id) != turn_id:
            continue
        if method == "error":
            raise _ProbeError("Codex 模型请求失败，本次未采用")
        if method == "model/rerouted":
            raise _ProbeError("Codex 切换了模型，本次未采用")
        if method in ("item/started", "item/completed"):
            item = params.get("item", {})
            if item.get("type") not in ("userMessage", "agentMessage", "reasoning"):
                raise _ProbeError("Codex 检测尝试调用工具或委派，本次未采用")
            if method == "item/completed" and item.get("type") == "agentMessage":
                messages[item.get("id")] = item
        if method == "thread/tokenUsage/updated":
            usage = params.get("tokenUsage", {}).get("total", {})
        if method == "turn/completed":
            finished = params.get("turn", {})
            if finished.get("id") != turn_id:
                continue
            if finished.get("status") != "completed" or finished.get("error"):
                raise _ProbeError("Codex 模型输出未完整结束，本次未采用")
            for item in finished.get("items", []):
                if item.get("type") not in ("userMessage", "agentMessage", "reasoning"):
                    raise _ProbeError("Codex 检测包含工具或委派，本次未采用")
                if item.get("type") == "agentMessage":
                    messages[item.get("id")] = item
            final = [
                item.get("text")
                for item in messages.values()
                if item.get("phase") in (None, "final_answer")
            ]
            if not final or not all(
                isinstance(text, str) and text.strip() for text in final
            ):
                raise _ProbeError("Codex 未返回完整的最终文本")
            return {
                "text": "\n".join(final),
                "runtime_model": MODEL,
                "runtime_effort": REASONING_EFFORT,
                # Thread configuration is not backend execution telemetry.
                "reported_model": None,
                "reported_effort": None,
                "input_tokens": _token_count(usage.get("inputTokens")),
                "output_tokens": _token_count(usage.get("outputTokens")),
            }


def _token_count(value):
    return value if type(value) is int and value >= 0 else None


async def _run(executable, directory, prompt, access_token, account_id, timeout):
    command = [executable, "app-server", "--stdio"]
    for key, value in _CONFIG.items():
        command.extend(["-c", f"{key}={json.dumps(value)}"])
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=directory,
        env=_process_environment(directory),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=_MAX_LINE_BYTES,
    )
    try:
        return await asyncio.wait_for(
            _conversation(process, directory, prompt, access_token, account_id),
            timeout=timeout,
        )
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


def request_probe(prompt, access_token, account_id, timeout=180):
    return asyncio.run(request_probe_async(prompt, access_token, account_id, timeout))


async def request_probe_async(prompt, access_token, account_id, timeout=180):
    """Generate one sample with isolated Codex, using in-memory subscription auth.

    Requires an installed CLI with app-server external-token auth and Ultra.
    No probe-level retries are added and no partial output is accepted.
    """
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("检测超时必须为正数")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("检测提示词不能为空")
    for value in (access_token, account_id):
        if not isinstance(value, str) or not value:
            raise ValueError("检测账号凭据为空或格式无效")
        if any(ord(char) < 33 or ord(char) > 126 for char in value):
            raise ValueError("检测账号凭据为空或格式无效")
    executable = _find_codex()
    try:
        with tempfile.TemporaryDirectory(prefix="sd-codex-probe-") as directory:
            return await _run(
                executable, directory, prompt, access_token, account_id, timeout
            )
    except _ProbeError:
        raise
    except (asyncio.TimeoutError, TimeoutError):
        raise ValueError("Codex 检测超时，本次未采用") from None
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("Codex 检测失败，请检查 CLI 版本、账号及网络") from None
