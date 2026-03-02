# OSS Revenue Calc

> **Show AI coding platforms what they theoretically owe the open source maintainers who make their products possible.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## What It Does

AI coding assistants (GitHub Copilot, Cursor, Tabnine, and others) generate code that imports open source packages at massive scale — yet OSS maintainers see none of that revenue. **OSS Revenue Calc** fetches real download statistics from PyPI and npm, applies configurable "Spotify model" revenue-share formulas, and produces detailed fair-compensation estimates you can drop straight into grant applications, advocacy materials, or funding negotiations.

---

## Quick Start

```bash
# Install
pip install oss-revenue-calc

# Calculate what GitHub Copilot theoretically owes the 'requests' maintainers
oss-revenue-calc calculate requests --platform copilot --ai-share 0.30

# Run against all built-in platforms at once
oss-revenue-calc calculate lodash --registry npm --all-platforms

# List available platform presets
oss-revenue-calc platforms
```

That's it. Real download numbers are fetched automatically — no API keys required.

---

## Features

- **Live download stats** — pulls 30/90/365-day counts directly from the PyPI Stats API and npm registry; no manual data entry needed.
- **Pro-rata (Spotify-style) model** — splits a platform's OSS revenue pool proportionally across packages by their AI-attributed download share.
- **Per-use model** — calculates a flat micro-payment per AI-attributed download, scaled by subscriber count and ARPU.
- **Built-in platform presets** — ships with conservative, research-backed configs for GitHub Copilot, Cursor, and Tabnine; all fields are editable.
- **Flexible output** — Rich-formatted terminal report for quick reads, plus JSON and CSV export for spreadsheets and advocacy decks.

---

## Usage Examples

### Basic calculation — PyPI package

```bash
oss-revenue-calc calculate requests --platform copilot --ai-share 0.30
```

```
╭─────────────────────────────────────────────────────────────╮
│           OSS Revenue Estimate — requests (PyPI)            │
╰─────────────────────────────────────────────────────────────╯

 Package          requests
 Registry         PyPI
 Period           365 days
 Total downloads  847,234,912
 AI share         30.0%  →  254,170,474 AI-attributed downloads

 Platform: GitHub Copilot
 ┌──────────────────┬──────────────┬──────────────┐
 │ Model            │ Annual       │ Monthly      │
 ├──────────────────┼──────────────┼──────────────┤
 │ Pro-Rata         │  $12,430.18  │   $1,035.85  │
 │ Per-Use          │   $7,625.11  │     $635.43  │
 └──────────────────┴──────────────┴──────────────┘
```

### npm package across all platforms

```bash
oss-revenue-calc calculate lodash --registry npm --all-platforms --ai-share 0.25
```

### Export results to CSV

```bash
oss-revenue-calc calculate numpy --platform copilot --ai-share 0.35 --output csv > numpy_estimate.csv
```

### Export results to JSON

```bash
oss-revenue-calc calculate numpy --platform cursor --ai-share 0.35 --output json
```

```json
[
  {
    "package_name": "numpy",
    "registry": "pypi",
    "platform": "cursor",
    "ai_share": 0.35,
    "prorata_annual": 9821.44,
    "prorata_monthly": 818.45,
    "peruse_annual": 6104.77,
    "peruse_monthly": 508.73
  }
]
```

### Override platform subscriber count or pricing

```bash
oss-revenue-calc calculate flask \
  --platform copilot \
  --ai-share 0.20 \
  --subscribers 2000000 \
  --price-per-user 19.00 \
  --oss-share 0.05
```

### List all built-in platform presets

```bash
oss-revenue-calc platforms
```

```
 slug        Name                Subscribers    Price/mo    OSS Pool %
 ─────────── ─────────────────── ────────────── ─────────── ──────────
 copilot     GitHub Copilot      1,500,000      $10.00      5.00%
 cursor      Cursor              500,000        $20.00      5.00%
 tabnine     Tabnine             300,000        $12.00      5.00%
```

---

## Revenue Models Explained

### Pro-Rata (Spotify-style)

The platform sets aside a fixed percentage of total subscription revenue as an "OSS pool". Each package earns a share of that pool proportional to its fraction of total AI-attributed downloads across all packages.

```
OSS Pool             = Annual Platform Revenue × OSS Revenue Share %
Package AI Downloads = Total Downloads × AI Share
Package Share        = Package AI Downloads ÷ Total Platform AI Downloads
Package Revenue      = OSS Pool × Package Share
```

### Per-Use

A flat micro-payment is made for every AI-attributed download, derived from platform ARPU and a configurable per-download rate.

```
Per-Download Rate  = (Subscribers × Monthly Price × OSS Share %) ÷ Total Monthly AI Downloads
Package Revenue    = Package AI Downloads × Per-Download Rate
```

---

## Project Structure

```
oss-revenue-calc/
├── pyproject.toml                  # Project metadata, deps, CLI entry point
├── README.md
├── oss_revenue_calc/
│   ├── __init__.py                 # Package init and version
│   ├── cli.py                      # Typer CLI — all commands and options
│   ├── fetcher.py                  # PyPI Stats + npm registry HTTP client
│   ├── models.py                   # PackageStats, PlatformConfig, RevenueResult
│   ├── calculator.py               # Pro-rata and per-use calculation engine
│   ├── report.py                   # Rich terminal report + JSON/CSV export
│   └── platforms.py                # Built-in platform presets
└── tests/
    ├── __init__.py
    ├── test_calculator.py          # Revenue model math and edge cases
    ├── test_fetcher.py             # Mocked HTTP tests for PyPI and npm
    └── test_report.py              # Report formatting and export correctness
```

---

## Configuration

All configuration is passed as CLI flags. There are no config files to edit — but you can override any platform preset value at the command line.

| Flag | Description | Default |
|---|---|---|
| `--platform` | Platform preset slug (`copilot`, `cursor`, `tabnine`) | `copilot` |
| `--all-platforms` | Run against all built-in presets | `false` |
| `--registry` | Package registry (`pypi` or `npm`) | `pypi` |
| `--ai-share` | Fraction of downloads attributed to AI-generated code (0.0–1.0) | `0.30` |
| `--period` | Download stat window in days (`30`, `90`, or `365`) | `365` |
| `--subscribers` | Override platform subscriber count | platform preset |
| `--price-per-user` | Override monthly price per subscriber (USD) | platform preset |
| `--oss-share` | Override OSS revenue pool percentage (0.0–1.0) | platform preset |
| `--total-platform-downloads` | Override total platform AI download estimate | auto-estimated |
| `--output` | Output format: `terminal`, `json`, or `csv` | `terminal` |

**Note on `--ai-share`:** There is no authoritative public data on what fraction of package downloads are driven by AI-generated code. `0.30` is a reasonable starting estimate; adjust it based on your own research and document your assumption clearly in any advocacy materials.

---

## Running Tests

```bash
pip install -e '.[dev]'
pytest
```

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

*Built with [Jitter](https://github.com/jitter-ai) — an AI agent that ships code daily.*
