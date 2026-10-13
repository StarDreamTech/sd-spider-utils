# ModelTrace attribution and provenance

This directory vendors the offline scoring code and unified reference bank from
[xqy2006/ModelTrace](https://github.com/xqy2006/ModelTrace), commit
[`6cd4a8ff0f3f4e49d6d6969dd2fbadfa1569fde2`](https://github.com/xqy2006/ModelTrace/tree/6cd4a8ff0f3f4e49d6d6969dd2fbadfa1569fde2),
retrieved 2026-10-13. Copyright (c) 2026 xqy2006; distributed under the
accompanying MIT [LICENSE](LICENSE).

Included upstream files and SHA-256 hashes:

| Upstream file | SHA-256 |
| --- | --- |
| `fingerprint.py` | `387fe5c44cc5f859995432267b0d3b462fc26e82419fc22e3ee7f36cc2502d98` |
| `data/unified_bank.json` | `f267d0513aa06981d024ec5394746fceddf44e4e8a75fa6bf8304255f4b32d6d` |
| `LICENSE` | `238afb57e498990742f84b9ce6167b4e256ac06104a9938ce953bc41c14bea51` |

Local adaptations: Python source is formatted with the project's Black formatter.
`fingerprint.py` loads `unified_bank.json` beside the module by
default instead of the upstream `data/gpt_bank.json`. Its scoring, parsing, and
challenge-generation algorithms are unchanged. `__init__.py` exposes
`load_bank`, `generate_challenges`, and `analyze_global_outputs` for internal use.
No upstream server, transport, collection tools, or raw reference responses are
included. The runtime dependency is NumPy (`>=1.26,<3`), plus Python's standard
library.

The bundled bank was built at `2026-10-09T06:24:27.469312+00:00` and contains
18 model labels including `gpt-6-astra`. It does not contain `gpt-6.1-sol`.
Model probabilities are normalized within this closed candidate set; an
unlisted model can still rank first as a different known candidate. These
scores measure output fingerprints, not task ability, and do not certify the
identity of an upstream service. The bank's calibration is not an independently
validated confidence threshold for Codex subscription requests using `ultra`
reasoning. No such threshold is added here.
