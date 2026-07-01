import json
import tempfile
import unittest
from pathlib import Path

from sd_spider_utils.common_utils import strtobool
from sd_spider_utils.data_utils import load_json_data
from sd_spider_utils.datetime_utils import extract_dates
from sd_spider_utils.text_utils import normalize_obj, normalize_text


class UtilityTests(unittest.TestCase):
    def test_text_and_date_helpers(self):
        self.assertEqual(normalize_text(" Ａ \n B "), "A B")
        self.assertEqual(normalize_obj({"name": " Ａ  B "}), {"name": "A B"})
        self.assertEqual(
            [
                date.strftime("%Y-%m-%d")
                for date in extract_dates("2026/6/30，2026年2月30日")
            ],
            ["2026-06-30"],
        )
        self.assertTrue(strtobool(" yes "))

    def test_json_and_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.jsonl"
            path.write_text(
                "\n".join(json.dumps({"id": value}) for value in (1, 2)),
                encoding="utf-8",
            )
            self.assertEqual(load_json_data(path), [{"id": 1}, {"id": 2}])
            path.write_text('{"id": 1}\nnot-json', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_json_data(path)


if __name__ == "__main__":
    unittest.main()
