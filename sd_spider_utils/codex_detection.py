"""Codex Astra/ultra 的离线指纹评分及本地结果缓存。"""

import asyncio
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time


MODEL = "gpt-6-astra"
REASONING_EFFORT = "ultra"
BANK_REVISION = "ModelTrace-6cd4a8ff"
WARNING = "仅为库内指纹排名，不证明模型身份、ultra 生效或能力下降；Astra 与 6.1 Sol 可能难以区分。"
STATUS_LABELS = {
    "target_first": "最像目标（仅供参考）",
    "other_first": "最像其他候选（待复测）",
    "error": "检测失败 / 无法判断",
}
RECORD_FIELDS = {
    "model",
    "reasoning_effort",
    "transport",
    "bank_revision",
    "checked_at",
    "status",
    "warning",
    "error",
    "prediction",
    "probability",
    "target_probability",
    "valid_outputs",
    "elapsed_seconds",
    "input_tokens",
    "output_tokens",
}


def prepare_detector():
    """在消耗额度前检查可选依赖和随包指纹库。"""
    try:
        from ._modeltrace import load_bank
    except ImportError:
        raise ValueError(
            "模型检测需要可选依赖：uv sync --locked --extra model-check"
        ) from None
    try:
        bank = load_bank()
        if MODEL not in {entry["id"] for entry in bank["models"]}:
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("随包模型指纹库缺失或损坏，请重新安装") from None
    return bank


def check_record(status, **fields):
    return {
        "model": MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "transport": "codex-app-server",
        "bank_revision": BANK_REVISION,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": status,
        "warning": WARNING,
        **fields,
    }


async def detect_model(access_token, account_id, timeout=180, bank=None):
    """并发执行三次独立挑战；失败取消剩余挑战，不重试、不更换型号。"""
    bank = bank if bank is not None else prepare_detector()
    from ._codex_probe import request_probe_async
    from ._modeltrace import analyze_global_outputs, generate_challenges
    from ._modeltrace.fingerprint import parse_numbers

    started = time.monotonic()
    challenges = generate_challenges(3)

    async def sample(challenge):
        response = await request_probe_async(
            challenge["prompt"], access_token, account_id, timeout=timeout
        )
        minimum = max(80, math.ceil(challenge["expected_count"] * 0.55))
        if len(parse_numbers(response["text"])) < minimum:
            raise ValueError(
                "模型未返回足够的有效整数，已停止检测；本次调用可能已消耗额度"
            )
        return response

    tasks = [asyncio.create_task(sample(challenge)) for challenge in challenges]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()
        responses = [task.result() for task in tasks]
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    outputs = [
        {"text": response["text"], "expected_count": challenge["expected_count"]}
        for challenge, response in zip(challenges, responses)
    ]
    scored = analyze_global_outputs(outputs, bank)
    expected = next(item for item in scored["results"] if item["model"] == MODEL)
    token_usage = {}
    for key in ("input_tokens", "output_tokens"):
        values = [response.get(key) for response in responses]
        token_usage[key] = (
            sum(values)
            if all(type(value) is int and value >= 0 for value in values)
            else None
        )
    return check_record(
        "target_first" if scored["prediction"] == MODEL else "other_first",
        prediction=scored["prediction"],
        probability=scored["probability"],
        target_probability=expected["probability"],
        valid_outputs=scored["used_outputs"],
        elapsed_seconds=round(time.monotonic() - started, 1),
        **token_usage,
    )


def cache_key(account_id):
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()


def cache_path(env_file):
    return Path(env_file).expanduser().with_suffix(".model-checks.json")


def _valid_record(record):
    if not isinstance(record, dict):
        return False
    if any(
        record.get(key) != value
        for key, value in (
            ("model", MODEL),
            ("reasoning_effort", REASONING_EFFORT),
            ("bank_revision", BANK_REVISION),
            ("transport", "codex-app-server"),
        )
    ):
        return False
    status = record.get("status")
    if not isinstance(status, str) or status not in STATUS_LABELS:
        return False
    try:
        when = datetime.fromisoformat(record["checked_at"])
        if when.tzinfo is None:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    if record["status"] == "error":
        return isinstance(record.get("error"), str)
    if not isinstance(record.get("prediction"), str):
        return False
    if record.get("valid_outputs") != 3:
        return False
    for key in ("probability", "target_probability"):
        value = record.get(key)
        if type(value) not in (int, float):
            return False
        if not 0 <= value <= 1:
            return False
    return True


def _clean_checks(payload):
    return {
        key: {field: item for field, item in value.items() if field in RECORD_FIELDS}
        for key, value in payload.items()
        if isinstance(key, str) and len(key) == 64 and _valid_record(value)
    }


def load_checks(env_file):
    """缓存只包含结果摘要，不保存凭据或原始模型回答。"""
    path = cache_path(env_file)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError("检测缓存无法读取；本次不展示旧结果") from None
    if not isinstance(payload, dict):
        raise ValueError("检测缓存格式无效；本次不展示旧结果")
    return _clean_checks(payload)


def save_checks(env_file, checks):
    """同目录原子替换；文件权限仅限当前用户，不写 env。"""
    path = cache_path(env_file)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = handle.name
            json.dump(
                _clean_checks(checks),
                handle,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            handle.write("\n")
        os.replace(temporary, path)
    except (OSError, ValueError):
        raise ValueError("检测结果未能保存；本次结果仍会显示") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
