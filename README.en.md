# sd_spider_utils

[简体中文](README.md) | [English](README.en.md)

Python helpers for cleaning text, extracting HTML, converting JSON Lines to Excel, managing browser sessions and choosing a download backend per Scrapy request.

## Install
```sh
pip install sd_spider_utils
```
Install just the extras you need: `excel`, `xpath`, `scrapy`, `requests-go`, `curl-cffi`, `drissionpage`, `scrapling`, `model-check`, or `all`. For example, `pip install 'sd_spider_utils[excel]'` adds pandas and openpyxl. With the Scrapling extra, `scrapling install` downloads its browser dependencies.

## Develop with uv
Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run `uv sync --locked` from the project root. The repository pins Python 3.12 via `.python-version`; uv creates `.venv` and installs the project in editable mode. Dependencies live in `pyproject.toml`; commit `uv.lock` with dependency changes. Use `uv sync --locked --all-extras` for all integrations or `uv run --extra NAME ...` for a specific one.

## Export Steam reviews
```sh
sd-steam-reviews --appid 246420 --language english
sd-steam-reviews --kingdom-rush 1 --language all
sd-steam-reviews --appid 246420 --output ./data/reviews.jl
sd-steam-reviews --help
```
One game per run. The default language is Simplified Chinese (`schinese`). This CLI needs no Steam account, cookie, API key or database. It previews the count and output path first; only an empty Enter confirms the write. The default JSON Lines path is `steam_reviews/<appid>_<language>.jl`. Each review carries collection metadata and a UTC timestamp. In a checkout, prefix these commands with `uv run`.

| Mode | Behavior |
| --- | --- |
| `auto` | Initialize a new file, then fetch new reviews on later runs; deduplicate by review ID. |
| `init` | Full initialization; refuses a non-empty output file. |
| `incremental` | Requires existing data; if there is no successful state, rescan and deduplicate first. |
| `full` | Rescan history and append only missing IDs, including reviews made public later. |

Keep the `.jl` file and `.jl.state.json` together. Don't run two writers against one file. Interrupted scans save a cursor in `.jl.resume.json`; retry the same command to resume, or use `--fresh` to disregard the cursor. `--page-size` accepts 1–100; the minimum request interval is one second.

## Codex quota CLI
```sh
uv run sd-codex-usage --env codex.env
uv run sd-codex-usage --env codex.env --json --timeout 20
```
Use a private env file for accounts you control. Keep its credentials out of Git. JSON output goes to stdout and progress to stderr. Exit codes are `0` for success, `1` for a failed query/check/write and `2` for an argument, configuration or dependency error. A stored token is a copy: signing in again elsewhere does not refresh this file. The legacy `base64rev:` representation is **not encryption**.

The optional `model-check` extra adds an active model fingerprint check via a local Codex CLI. It consumes inference quota; ordinary quota queries need not run it. Read `sd-codex-usage --help` for account selection and output controls before enabling checks. Results depend on the installed CLI and are distinct from authentication or quota errors.

## Library functions
| Task | Helpers |
| --- | --- |
| Normalize text and nested values | `normalize_text`, `normalize_obj`, `clean_text`, `strtobool` |
| Detect characters and dates | `contains_chinese`, `contains_date`, `extract_dates` |
| Extract HTML text | `get_text_bs4`, `get_text_xpath`, `get_text_scrapy` |
| Read JSON/JSONL and write spreadsheets | `load_json_data`, `data2excel`, `json2excel` |
| Select HTTP clients | `request_with_requests_go`, `request_with_curl_cffi` |

```python
from sd_spider_utils import normalize_obj

print(normalize_obj({"name": "  Ａ   B  "}))
```

## Browser helpers and Scrapy
With the `drissionpage` extra, `get_browser` reuses one session per `browser_type`; the first configuration applies until `close_browser` or `close_all_browsers`. `save_page`, `download_page` and `get_html_from_chrome` handle page output, resource downloads and rendered HTML respectively.

Register a single downloader router:
```python
DOWNLOADER_MIDDLEWARES = {
    "sd_spider_utils.middlewares.BackendRouterMiddleware": 950,
}
```
`Request.meta['download_backend']` selects `scrapy`, `requests_go`, `curl_cffi`, `dp`, `dp_listen` or `scrapling`. The listener backend also needs `listen_path`. The default third-party timeout is 30 seconds. TLS verification defaults to enabled for the requests-go and curl-cffi clients.

## Checks and releases
```sh
uv run --locked python -m unittest discover -s tests
uv run --locked black --check sd_spider_utils tests
uv run --locked flake8 --ignore=E501 sd_spider_utils tests
uv build
```
Before tagging a release, check the version and lockfile, inspect the staged diff, and exclude account env files, local data and detection caches. Publishing is tag-driven.
