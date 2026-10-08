#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Steam 评测导出器（Python 3.10+，无需账号、API Key 或数据库）。

每次只采集一个游戏。首次初始化，之后按发布时间倒序采集新增评测并按 ID 去重。
    sd-steam-reviews --kingdom-rush 1 --language schinese
    sd-steam-reviews --appid 246420 --language all
    sd-steam-reviews --appid 246420 --language schinese --mode incremental

--kingdom-rush 1~5 分别为：初代、前线、起源、复仇、联盟。
默认文件：当前工作目录下 steam_reviews/<appid>_<language>.jl。
首次请求预览总数，只有直接按回车才开始写文件；输入其他内容或 Ctrl+C 取消。
每行保留一条完整 API 评测，额外的 _collection 保存游戏、查询语言和抓取时间。

增量只新增未见 ID，不覆盖已保存评测的修改，也不删除源站已消失的评测。
初始化完成后，在 .jl.state.json 保存成功时间边界；后续读到更早的评测就停止。
同一秒的评测会全部检查，已有 ID 跳过。失败不推进边界，重新执行同一命令补采。
状态文件需与 JL 一起保留；未完成初始化或没有状态文件时，先去重补齐完整初始化。
--mode full 可手动扫描全部历史，补充延迟公开或后来改成目标语言的旧评测。
不要同时运行两个任务写同一文件。
“全部”指接口当前公开可返回的评测，不包括被删除或无权访问的内容。
文档：https://partner.steamgames.com/doc/webapi/IUserReviewsService
"""

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


KINGDOM_RUSH = {
    1: (246420, "王国保卫战 1 / Kingdom Rush"),
    2: (458710, "王国保卫战 2：前线 / Frontiers"),
    3: (816340, "王国保卫战 3：起源 / Origins"),
    4: (1367550, "王国保卫战 4：复仇 / Vengeance"),
    5: (2849080, "王国保卫战 5：联盟 / Alliance"),
}


def review_id(review):
    """读取稳定评测 ID；坏记录直接报错，不写入无法去重的数据。"""
    value = review.get("recommendationid") if isinstance(review, dict) else None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise ValueError("评测缺少有效的 recommendationid")
    return value


def validate_page(payload, language):
    """验证整页后再写入，避免把错误响应或错误语言当作成功数据。"""
    if not isinstance(payload, dict):
        raise ValueError("Steam 返回失败结果或响应结构无效")
    reviews = payload.get("reviews")
    # Web API 的空页会省略 reviews；仅在明确返回零条时视为空页。
    summary = payload.get("query_summary")
    if (
        "reviews" not in payload
        and isinstance(summary, dict)
        and summary.get("num_reviews") == 0
    ):
        payload = {**payload, "reviews": []}
        reviews = payload["reviews"]
    if not isinstance(reviews, list):
        raise ValueError("Steam 响应缺少 reviews 列表")
    for review in reviews:
        review_id(review)
        if not isinstance(review.get("review"), str):
            raise ValueError("Steam 评测缺少正文")
        if (
            type(review.get("timestamp_created")) is not int
            or review["timestamp_created"] < 0
        ):
            raise ValueError("Steam 评测缺少有效的发布时间")
        if language != "all" and review.get("language") != language:
            raise ValueError("Steam 返回了与筛选条件不符的评测语言，停止写入")
    if reviews and not isinstance(payload.get("cursor"), str):
        raise ValueError("Steam 非空评测页缺少分页游标")
    return payload


def retry_delay(retry_after, attempt):
    """尊重 Retry-After；长时间限流直接退出，留待稍后重新运行。"""
    delay = 2 ** (attempt + 1)
    if retry_after:
        try:
            delay = max(delay, float(retry_after))
        except ValueError:
            try:
                until = parsedate_to_datetime(retry_after)
                delay = max(delay, (until - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    if not math.isfinite(delay) or delay > 60:
        raise RuntimeError("Steam 要求较长时间后重试，请稍后重新运行；已保存数据保留")
    return delay


class ReviewClient:
    """串行读取 Steam 游标分页，限制频率，仅对暂时性网络故障有限重试。"""

    def __init__(self, appid, language, page_size=100, interval=1.0):
        """固定单个游戏和筛选条件，记录本次实际 HTTP 请求次数。"""
        self.appid = appid
        self.language = language
        self.page_size = page_size
        self.interval = interval
        self.requests = 0
        self.last_request_at = None

    def fetch(self, cursor):
        """返回已验证的一页；400/401/403 等不重试，429/5xx 最多重试三次。"""
        params = {
            "appid": self.appid,
            "languages": [self.language],
            "filter": 1,
            "review_type": 0,
            "purchase_type": 1,
            "filter_offtopic_activity": False,
            "num_per_page": self.page_size,
            "cursor": cursor,
        }
        request = Request(
            "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/?"
            + urlencode({"input_json": json.dumps(params)}),
            headers={
                "User-Agent": "SteamReviewExport/1.0",
                "Accept": "application/json",
            },
        )
        for attempt in range(4):
            if self.last_request_at is not None:
                time.sleep(
                    max(0, self.interval - (time.monotonic() - self.last_request_at))
                )
            self.last_request_at = time.monotonic()
            self.requests += 1
            retry_after = None
            try:
                with urlopen(request, timeout=30) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict):
                    raise ValueError("Steam 返回无效响应")
                return validate_page(payload.get("response"), self.language)
            except HTTPError as error:
                status = error.code
                retry_after = error.headers.get("Retry-After")
                error.close()
                if status != 429 and not 500 <= status <= 599:
                    raise RuntimeError(
                        f"Steam 请求失败：HTTP {status}，未扩大请求"
                    ) from None
                reason = f"HTTP {status}"
            except (URLError, TimeoutError, ConnectionError, IncompleteRead) as error:
                reason = type(error).__name__
            if attempt == 3:
                raise RuntimeError(f"Steam 请求失败：{reason}，已达到重试上限")
            delay = retry_delay(retry_after, attempt)
            print(
                f"请求暂时失败（{reason}），{delay:g} 秒后重试 {attempt + 1}/3…",
                flush=True,
            )
            time.sleep(delay)


def load_existing(path, appid, language):
    """读取 JL 的已有 ID 并核对任务身份；损坏行必须修复，不静默丢弃。"""
    ids = set()
    if not path.exists():
        return ids
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                identity = review_id(item)
                metadata = item.get("_collection")
                if not isinstance(metadata, dict) or (
                    metadata.get("appid") != appid
                    or metadata.get("language") != language
                ):
                    raise ValueError("文件属于其他游戏/语言，或缺少本脚本的任务元信息")
            except (ValueError, TypeError) as error:
                raise ValueError(
                    f"{path} 第 {line_number} 行无效：{error}；未改动原文件"
                ) from None
            ids.add(identity)
    return ids


def load_checkpoint(output, appid, language):
    """只使用已成功完成的边界；缺少基线或 JL 被截短时重新补齐初始化。"""
    path = output.with_name(output.name + ".state.json")
    if not path.exists() or not output.exists():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or (
        state.get("appid") != appid
        or state.get("language") != language
        or type(state.get("newest_created_at")) is not int
        or state["newest_created_at"] < 0
        or type(state.get("file_size")) is not int
        or state["file_size"] < 0
    ):
        raise ValueError(
            "采集状态文件无效或不属于本任务，可使用 --mode full 重新建立基线"
        )
    if output.stat().st_size < state["file_size"]:
        return None
    return state["newest_created_at"]


def save_checkpoint(output, client, newest_created_at):
    """JL 成功写入后才原子替换状态；中断或请求失败保留上次成功边界。"""
    path = output.with_name(output.name + ".state.json")
    temporary = path.with_name(path.name + ".tmp")
    state = {
        "appid": client.appid,
        "language": client.language,
        "newest_created_at": newest_created_at,
        "file_size": output.stat().st_size,
    }
    temporary.write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def collect(client, first_page, output, known_ids, cutoff=None):
    """倒序去重追加；有成功基线时跨过时间边界即停，同秒记录不提前跳过。"""
    page = first_page
    cursors = {"*"}
    added = scanned = pages = 0
    newest_created_at = cutoff or 0
    previous_created_at = None
    reached_cutoff = False
    output.parent.mkdir(parents=True, exist_ok=True)
    # 有效 JSON 的最后一行可能没有换行，追加前补一个行分隔符。
    needs_newline = False
    if output.exists() and output.stat().st_size:
        with output.open("rb") as stream:
            stream.seek(-1, 2)
            needs_newline = stream.read(1) != b"\n"
    with output.open("a", encoding="utf-8", newline="\n") as stream:
        while True:
            reviews = validate_page(page, client.language)["reviews"]
            if not reviews:
                break
            timestamps = [review["timestamp_created"] for review in reviews]
            if (
                previous_created_at is not None and timestamps[0] > previous_created_at
            ) or any(
                earlier < later for earlier, later in zip(timestamps, timestamps[1:])
            ):
                raise ValueError("Steam 评测未按发布时间倒序返回，停止采集且不推进边界")
            previous_created_at = timestamps[-1]
            newest_created_at = max(newest_created_at, timestamps[0])
            cursor = page["cursor"]
            if not cursor or cursor in cursors:
                raise RuntimeError(
                    "Steam 分页游标重复或未推进，未完成采集；已保存数据保留"
                )
            cursors.add(cursor)
            pages += 1
            observed_at = datetime.now(timezone.utc).isoformat()
            for review in reviews:
                if cutoff is not None and review["timestamp_created"] < cutoff:
                    reached_cutoff = True
                    break
                scanned += 1
                identity = review_id(review)
                if identity in known_ids:
                    continue
                item = dict(review)
                item["_collection"] = {
                    "source_platform": "steam",
                    "appid": client.appid,
                    "language": client.language,
                    "collected_at": observed_at,
                }
                if needs_newline:
                    stream.write("\n")
                    needs_newline = False
                stream.write(json.dumps(item, ensure_ascii=False) + "\n")
                known_ids.add(identity)
                added += 1
            stream.flush()
            print(
                f"第 {pages} 页：{len(reviews)} 条 | 已扫描 {scanned} | 新增 {added} | 跳过 {scanned - added}",
                flush=True,
            )
            if reached_cutoff:
                print("已越过上次成功采集的发布时间边界，停止请求后续旧评论。")
                break
            page = client.fetch(cursor)
        stream.flush()
        os.fsync(stream.fileno())
    save_checkpoint(output, client, newest_created_at)
    print(f"采集完成：扫描 {scanned} 条，新增 {added} 条，跳过 {scanned - added} 条。")
    print(
        f"本地唯一评论 {len(known_ids)} 条；实际 HTTP 请求 {client.requests} 次（含预览、末页及重试）。"
    )
    print(f"文件：{output.resolve()}")
    return added


def build_parser():
    """构造单任务命令行；auto 自动判断初始化或增量，init 永不覆盖非空文件。"""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    game = parser.add_mutually_exclusive_group(required=True)
    game.add_argument("--appid", type=int, help="任意 Steam 游戏的 AppID")
    game.add_argument(
        "--kingdom-rush",
        type=int,
        choices=KINGDOM_RUSH,
        metavar="{1,2,3,4,5}",
        help="王国保卫战第几代",
    )
    parser.add_argument(
        "--language",
        default="schinese",
        help="Steam 语言代码，如 schinese（简中）、tchinese、english、all（全部）",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "init", "incremental", "full"],
        default="auto",
        help="auto：完整初始化后自动快速增量；full：手动全历史去重补采",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="输出 .jl 路径，默认 steam_reviews/<appid>_<language>.jl",
    )
    parser.add_argument(
        "--page-size", type=int, default=100, help="每页 1~100 条，默认 100"
    )
    parser.add_argument(
        "--interval", type=float, default=1, help="请求最小间隔（秒），至少 1，默认 1"
    )
    return parser


def main(argv=None):
    """预览数量后等待回车授权，取消不创建数据文件，失败返回非零退出码。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    appid, name = (
        KINGDOM_RUSH[args.kingdom_rush]
        if args.kingdom_rush
        else (args.appid, f"Steam AppID {args.appid}")
    )
    language = args.language.strip().lower()
    if appid <= 0 or not re.fullmatch(r"[a-z][a-z_]*", language):
        parser.error("AppID 必须为正整数；语言请使用 Steam 代码，如 schinese 或 all")
    if (
        not 1 <= args.page_size <= 100
        or not math.isfinite(args.interval)
        or args.interval < 1
    ):
        parser.error("每页必须为 1~100；请求间隔必须为至少 1 秒的有限数值")
    output = args.output or Path("steam_reviews") / f"{appid}_{language}.jl"
    try:
        nonempty = output.exists() and output.stat().st_size > 0
        if args.mode == "init" and nonempty:
            raise ValueError(
                "初始化不会覆盖已有文件。请更换 --output，或使用 --mode incremental"
            )
        if args.mode == "incremental" and not output.exists():
            raise ValueError("增量文件不存在，请先使用 --mode init 或默认 auto 初始化")
        known_ids = load_existing(output, appid, language)
        cutoff = (
            load_checkpoint(output, appid, language)
            if args.mode not in {"init", "full"}
            else None
        )
        mode = (
            "增量（按发布时间倒序，遇到历史边界即停）"
            if cutoff is not None
            else (
                "全历史去重补采"
                if args.mode == "full"
                else "补齐初始化（尚无完整基线）" if known_ids else "初始化"
            )
        )
        client = ReviewClient(appid, language, args.page_size, args.interval)
        first_page = client.fetch("*")
        summary = first_page.get("query_summary")
        total = first_page.get("total_matching")
        if total is None and isinstance(summary, dict):
            total = summary.get("total_reviews")
        if type(total) is not int or total < 0:
            raise ValueError("Steam 未提供有效的符合条件的评论总数，无法预览，停止采集")
        print(f"\n游戏：{name}（{appid}）\n语言：{language}\n模式：{mode}")
        print("范围：全部好差评、全部购买来源、包含离题评测（接口可公开返回的部分）")
        print(f"符合条件的评论总数：{total:,} 条\n每页最多：{args.page_size} 条")
        if cutoff is None:
            expected = math.ceil(total / args.page_size) + 1
            print(f"预计 HTTP 请求：约 {expected:,} 次（本次完整扫描，含末尾空页确认）")
        else:
            boundary = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
            print(f"增量时间边界：{boundary}（同一秒也检查，已有 ID 跳过）")
            if not first_page["reviews"] or any(
                r["timestamp_created"] < cutoff for r in first_page["reviews"]
            ):
                print("预计 HTTP 请求：1 次（首屏已覆盖增量范围，无需继续请求旧页）")
            else:
                print("预计 HTTP 请求：至少 2 次，首屏尚未越过时间边界，读到边界即停。")
                print("接口不提供此时间段的新增总数，无法提前准确估算页数。")
        print(f"预览已请求 {client.requests} 次，确认后复用首屏。")
        print("估算不含重试；实际分页可能不足一页，采集期间总数也可能变化。")
        print(f"本地已有唯一 ID：{len(known_ids):,} 个\n输出：{output.resolve()}")
        if known_ids and cutoff is None:
            print(
                "本次先完整扫描并去重，完成后建立增量边界；后续运行只请求新增时间段。"
            )
        if input("\n确认请直接按回车开始；输入任意文字再回车取消：") != "":
            print("已取消，未写入文件。")
            return 0
        collect(client, first_page, output, known_ids, cutoff=cutoff)
        return 0
    except EOFError:
        print("未收到回车确认，已取消，未写入文件。")
        return 0
    except KeyboardInterrupt:
        print(
            "\n已中断；已写入的完整记录保留，可重新运行同一命令去重补采。",
            file=sys.stderr,
        )
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(f"\n采集未完成：{error}", file=sys.stderr)
        return 1


def cli():
    """安装命令和 python -m 共用入口，保证 Windows 管道日志使用 UTF-8。"""
    # Windows 重定向/管道的默认编码可能是 GBK，统一 UTF-8 以保留中文日志。
    for console in (sys.stdout, sys.stderr):
        if hasattr(console, "reconfigure"):
            console.reconfigure(encoding="utf-8", errors="backslashreplace")
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())
