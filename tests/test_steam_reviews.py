"""Steam 导出的分页、增量边界、文件保护和公开 API 协议。"""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

from sd_spider_utils import steam_reviews as steam


def review(identity, created=30, language="schinese"):
    return {
        "recommendationid": str(identity),
        "review": "好玩\n值得推荐",
        "language": language,
        "timestamp_created": created,
    }


def page(*reviews, cursor="next", total=3):
    return {
        "reviews": list(reviews),
        "cursor": cursor,
        "query_summary": {"num_reviews": len(reviews), "total_reviews": total},
        "total_matching": total,
    }


def client(*responses):
    instance = steam.ReviewClient(246420, "schinese")
    instance.fetch = Mock(side_effect=responses)
    return instance


class SteamReviewsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name) / "reviews.jl"
        self.log = io.StringIO()
        for redirect in (
            contextlib.redirect_stdout(self.log),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            redirect.__enter__()
            self.addCleanup(redirect.__exit__, None, None, None)

    def baseline(self):
        steam.collect(
            client(page()), page(review(3), review(2, 20)), self.output, set()
        )
        return steam.load_existing(self.output, 246420, "schinese")

    def test_full_scan_deduplicates_and_does_not_stop_at_short_page(self):
        known = self.baseline()
        fake = client(page(review(2, 20), review(1, 10), cursor="b"), page())
        first = page(review(4, 40), {**review(3), "review": "已修改"})
        self.assertEqual(steam.collect(fake, first, self.output, known), 2)
        rows = [
            json.loads(line) for line in self.output.read_text("utf-8").splitlines()
        ]
        self.assertEqual([r["recommendationid"] for r in rows], ["3", "2", "4", "1"])
        self.assertEqual(rows[0]["review"], "好玩\n值得推荐")
        self.assertEqual(rows[0]["_collection"]["appid"], 246420)
        self.assertEqual(fake.fetch.call_count, 2)

    def test_failed_initialization_resumes_without_checkpoint(self):
        with self.assertRaisesRegex(RuntimeError, "timeout"):
            steam.collect(
                client(RuntimeError("timeout")), page(review(3)), self.output, set()
            )
        self.assertIsNone(steam.load_checkpoint(self.output, 246420, "schinese"))
        known = steam.load_existing(self.output, 246420, "schinese")
        self.assertEqual(known, {"3"})
        self.assertEqual(
            steam.collect(
                client(page()), page(review(3), review(2, 20)), self.output, known
            ),
            1,
        )

    def test_incremental_boundary_and_same_second_across_pages(self):
        known = self.baseline()
        fake = client(page(review(4), review(2, 20), cursor="b"))
        self.assertEqual(
            steam.collect(
                fake, page(review(5, 50), review(3)), self.output, known, cutoff=30
            ),
            2,
        )
        self.assertEqual(fake.fetch.call_count, 1)
        self.assertEqual(known, {"2", "3", "4", "5"})
        self.assertEqual(steam.load_checkpoint(self.output, 246420, "schinese"), 50)
        no_new = client()
        self.assertEqual(
            steam.collect(
                no_new, page(review(5, 50), review(3)), self.output, known, cutoff=50
            ),
            0,
        )
        no_new.fetch.assert_not_called()

    def test_failed_incremental_preserves_successful_boundary(self):
        known = self.baseline()
        with self.assertRaises(RuntimeError):
            steam.collect(
                client(RuntimeError("timeout")),
                page(review(6, 60)),
                self.output,
                known,
                cutoff=30,
            )
        self.assertEqual(steam.load_checkpoint(self.output, 246420, "schinese"), 30)
        known = steam.load_existing(self.output, 246420, "schinese")
        self.assertEqual(
            steam.collect(
                client(),
                page(review(6, 60), review(5, 50), review(2, 20)),
                self.output,
                known,
                cutoff=30,
            ),
            1,
        )
        self.assertEqual(steam.load_checkpoint(self.output, 246420, "schinese"), 60)

    def test_missing_newline_and_duplicate_within_page(self):
        known = self.baseline()
        self.output.write_bytes(self.output.read_bytes().rstrip(b"\n"))
        self.assertEqual(
            steam.collect(
                client(page()), page(review(4), review(4)), self.output, known
            ),
            1,
        )
        self.assertEqual(len(self.output.read_text("utf-8").splitlines()), 3)

    def test_wrong_scope_corruption_and_truncated_checkpoint(self):
        self.baseline()
        original = self.output.read_bytes()
        for appid, language in [(458710, "schinese"), (246420, "all")]:
            with self.subTest(appid=appid, language=language):
                with self.assertRaises(ValueError):
                    steam.load_existing(self.output, appid, language)
                with self.assertRaises(ValueError):
                    steam.load_checkpoint(self.output, appid, language)
        self.assertEqual(self.output.read_bytes(), original)
        self.output.write_bytes(original + b'{"broken":')
        with self.assertRaisesRegex(ValueError, "第 3 行"):
            steam.load_existing(self.output, 246420, "schinese")
        self.output.write_bytes(b"")
        self.assertIsNone(steam.load_checkpoint(self.output, 246420, "schinese"))

    def test_invalid_page_sort_and_cursor_never_commit_checkpoint(self):
        for first, next_pages, error in [
            (page(review(1), {}), [], ValueError),
            (page(review(2, 20), review(3)), [], ValueError),
            (page(review(2, 20)), [page(review(3))], ValueError),
            (page(review(3)), [page(review(2, 20))], RuntimeError),
        ]:
            with self.subTest(first=first, error=error):
                with self.assertRaises(error):
                    steam.collect(client(*next_pages), first, self.output, set())
                self.assertIsNone(
                    steam.load_checkpoint(self.output, 246420, "schinese")
                )

    def test_preview_cancel_eof_confirm_and_init_protection(self):
        output = self.output.parent / "new" / "reviews.jl"
        args = ["--kingdom-rush", "1", "--output", str(output)]
        for answer in ["cancel", EOFError()]:
            fake = client(page(review(1), total=1))
            with (
                patch.object(steam, "ReviewClient", return_value=fake),
                patch("builtins.input", side_effect=[answer]),
            ):
                self.assertEqual(steam.main(args), 0)
            self.assertFalse(output.parent.exists())
        fake = client(page(review(1), total=1), page())
        with (
            patch.object(steam, "ReviewClient", return_value=fake),
            patch("builtins.input", return_value=""),
        ):
            self.assertEqual(steam.main(args), 0)
            self.assertEqual(steam.main(args + ["--mode", "init"]), 1)
        self.assertEqual(
            [c.args for c in fake.fetch.call_args_list], [("*",), ("next",)]
        )
        self.assertIn("评论总数：1 条", self.log.getvalue())

    def test_incremental_preview_cancel_preserves_state(self):
        self.baseline()
        original = self.output.read_bytes()
        fake = client(page(review(4, 40), review(3), review(2, 20), total=17000))
        with (
            patch.object(steam, "ReviewClient", return_value=fake),
            patch("builtins.input", return_value="cancel"),
        ):
            self.assertEqual(
                steam.main(["--appid", "246420", "--output", str(self.output)]), 0
            )
        self.assertIn("预计 HTTP 请求：1 次", self.log.getvalue())
        self.assertEqual(self.output.read_bytes(), original)
        self.assertEqual(steam.load_checkpoint(self.output, 246420, "schinese"), 30)

    def test_web_api_parameters_cursor_encoding_and_retry(self):
        payload = page(review(1, language="english"))
        opener = Mock(
            side_effect=[
                HTTPError(
                    "https://api.steampowered.com/",
                    429,
                    "rate limit",
                    {"Retry-After": "3"},
                    None,
                ),
                io.BytesIO(json.dumps({"response": payload}).encode()),
            ]
        )
        with (
            patch.object(steam, "urlopen", opener),
            patch.object(steam.time, "sleep") as sleep,
        ):
            instance = steam.ReviewClient(246420, "all", page_size=50)
            self.assertEqual(instance.fetch("a+/="), payload)
        url = urlparse(opener.call_args.args[0].full_url)
        self.assertEqual(url.netloc, "api.steampowered.com")
        params = json.loads(parse_qs(url.query)["input_json"][0])
        self.assertEqual(
            params,
            dict(
                appid=246420,
                languages=["all"],
                filter=1,
                review_type=0,
                purchase_type=1,
                filter_offtopic_activity=False,
                num_per_page=50,
                cursor="a+/=",
            ),
        )
        self.assertEqual(instance.requests, 2)
        sleep.assert_any_call(3.0)
        with self.assertRaisesRegex(RuntimeError, "较长时间"):
            steam.retry_delay("120", 0)

    def test_forbidden_is_not_retried_and_network_retries_are_bounded(self):
        for error, calls in [
            (HTTPError("https://api.steampowered.com/", 403, "forbidden", {}, None), 1),
            (URLError("timeout"), 4),
        ]:
            with (
                self.subTest(error=error),
                patch.object(steam, "urlopen", side_effect=error) as opener,
                patch.object(steam.time, "sleep"),
            ):
                with self.assertRaises(RuntimeError):
                    steam.ReviewClient(246420, "schinese").fetch("*")
                self.assertEqual(opener.call_count, calls)

    def test_empty_web_api_page_and_malformed_responses(self):
        empty = {
            "query_summary": {"num_reviews": 0},
            "cursor": "end",
            "total_matching": 30,
        }
        with patch.object(
            steam,
            "urlopen",
            return_value=io.BytesIO(json.dumps({"response": empty}).encode()),
        ):
            self.assertEqual(
                steam.ReviewClient(246420, "schinese").fetch("*")["reviews"], []
            )
        for invalid in [
            None,
            {},
            {"reviews": None},
            page(review(1, language="english")),
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                steam.validate_page(invalid, "schinese")

    def test_invalid_arguments_do_not_request_network(self):
        with patch.object(steam, "urlopen") as opener:
            for args in [
                [],
                ["--appid", "0"],
                ["--appid", "1", "--interval", "nan"],
                ["--appid", "1", "--page-size", "101"],
            ]:
                with self.subTest(args=args), self.assertRaises(SystemExit) as raised:
                    steam.main(args)
                self.assertEqual(raised.exception.code, 2)
            self.assertEqual(
                steam.main(
                    [
                        "--appid",
                        "1",
                        "--mode",
                        "incremental",
                        "--output",
                        str(self.output),
                    ]
                ),
                1,
            )
            opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
