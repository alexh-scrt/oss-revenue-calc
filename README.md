# OSS Revenue Calc

> **Calculate how much revenue AI coding platforms would theoretically owe open source maintainers under the proposed "Spotify model" for AI-generated package usage.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## What Is This?

AI coding assistants (GitHub Copilot, Cursor, Tabnine, etc.) generate code that imports and uses open source packages at massive scale. The "Spotify model" proposes that a portion of platform subscription revenue should flow back to OSS maintainers, proportional to how often their packages are used in AI-generated code.

**OSS Revenue Calc** fetches real download statistics from PyPI and npm, then runs configurable revenue-share models to produce detailed fair-compensation estimates you can use in grant applications, advocacy materials, or funding negotiations.

---

## Installation

```bash
# From PyPI (once published)
pip install oss-revenue-calc

# From source
git clone https://github.com/example/oss-revenue-calc
cd oss-revenue-calc
pip install -e ".[dev]"
```

---

## Quick Start

### Estimate revenue for a single PyPI package

```bash
oss-revenue-calc calculate requests --platform copilot --ai-share 0.30
```

### Estimate for an npm package

```bash
oss-revenue-calc calculate lodash --registry npm --platform cursor --ai-share 0.25
```

### Compare across all built-in platforms

```bash
oss-revenue-calc calculate numpy --all-platforms --ai-share 0.40
```

### Export results to JSON or CSV

```bash
oss-revenue-calc calculate pandas --platform copilot --ai-share 0.35 --output json > results.json
oss-revenue-calc calculate pandas --platform copilot --ai-share 0.35 --output csv > results.csv
```

### Use a custom platform configuration

```bash
oss-revenue-calc calculate flask \
  --platform custom \
  --subscribers 5000000 \
  --arpu 15.00 \
  --revenue-share-pct 0.05 \
  --ai-share 0.20
```

### List available built-in platforms

```bash
oss-revenue-calc platforms
```

---

## Revenue Models

### 1. Spotify-Style Pro-Rata Model

The platform designates a fixed percentage of total subscription revenue as the "OSS pool." Each package receives a share of that pool proportional to its share of total AI-attributed downloads across all packages on the platform.

```
OSS Pool = Total Platform Revenue × Revenue Share %
Package Share = AI-Attributed Downloads (package) / AI-Attributed Downloads (all packages)
Package Revenue = OSS Pool × Package Share
```

**Inputs needed:**
- Platform total annual revenue (subscribers × ARPU × 12)
- Platform OSS revenue share percentage
- Package's AI-attributed downloads relative to platform total

### 2. Per-Use Micro-Payment Model

The platform pays a flat micro-payment for each AI-attributed download event, scaled by subscriber count and average revenue per user.

```
AI Downloads = Total Downloads × AI Share %
Per-Download Rate = (ARPU × Revenue Share %) / Downloads Per Subscriber Per Month
Annual Revenue = AI Downloads × Per-Download Rate × 12
```

**Inputs needed:**
- Package total downloads (fetched automatically)
- AI download share percentage (your estimate)
- Platform ARPU and subscriber count
- Assumed downloads per subscriber per month

---

## Built-In Platforms

| Platform | Subscribers | Monthly ARPU | OSS Share % |
|----------|------------|--------------|-------------|
| GitHub Copilot | 1,300,000 | $10.00 | 5% |
| Cursor | 300,000 | $20.00 | 5% |
| Tabnine | 1,000,000 | $12.00 | 5% |
| Amazon CodeWhisperer | 500,000 | $19.00 | 5% |

> **Note:** Subscriber counts and pricing are estimates based on public reporting and may not reflect current figures. Use `--subscribers` and `--arpu` to override with your own research.

---

## Example Output

```
╭─────────────────────────────────────────────────────────────────────────╮
│              OSS Revenue Estimate: requests (PyPI)                      │
╰─────────────────────────────────────────────────────────────────────────╯

📦 Package Stats (last 365 days)
  Registry:           PyPI
  Total Downloads:    847,234,912
  AI-Attributed:       254,170,474  (30.0% of total)
  Period:             365 days

🤖 Platform: GitHub Copilot
  Subscribers:        1,300,000
  Monthly ARPU:       $10.00
  Annual Revenue:     $156,000,000
  OSS Pool (5%):      $7,800,000

💰 Revenue Estimates
  ┌─────────────────────┬──────────────┬──────────────┐
  │ Model               │ Annual       │ Monthly      │
  ├─────────────────────┼──────────────┼──────────────┤
  │ Pro-Rata            │ $12,450.23   │ $1,037.52    │
  │ Per-Use             │ $8,322.15    │ $693.51      │
  │ Average             │ $10,386.19   │ $865.52      │
  └─────────────────────┴──────────────┴──────────────┘

📊 Assumptions
  AI download share:  30.0%
  Platform OSS pool:  0.016% of all PyPI downloads are requests
```

---

## CLI Reference

### `oss-revenue-calc calculate <package>`

Calculate revenue estimates for a package.

| Option | Default | Description |
|--------|---------|-------------|
| `--registry` | `pypi` | Package registry (`pypi` or `npm`) |
| `--platform` | `copilot` | Platform preset name |
| `--all-platforms` | `False` | Run for all built-in platforms |
| `--ai-share` | `0.30` | Fraction of downloads attributed to AI (0.0–1.0) |
| `--subscribers` | (platform default) | Override subscriber count |
| `--arpu` | (platform default) | Override monthly ARPU in USD |
| `--revenue-share-pct` | (platform default) | Override OSS revenue share fraction |
| `--period` | `365` | Download period in days (30, 90, or 365) |
| `--output` | `terminal` | Output format: `terminal`, `json`, or `csv` |
| `--model` | `both` | Revenue model: `prorata`, `peruse`, or `both` |

### `oss-revenue-calc platforms`

List all built-in platform configurations.

### `oss-revenue-calc version`

Print the tool version.

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with verbose output
pytest -v
```

---

## The Case for OSS Revenue Sharing

AI coding assistants are trained on and actively suggest code patterns drawn from open source repositories. When a developer uses Copilot to write `import requests; response = requests.get(...)`, the `requests` library's API design, documentation, and the years of maintainer work that shaped it are directly monetized — without any compensation flowing back.

The Spotify model offers a precedent: streaming platforms pay rights holders based on play counts. A similar mechanism for AI coding platforms would:

1. **Create sustainable funding** for critical OSS infrastructure
2. **Align incentives** — platforms benefit when packages are well-maintained
3. **Scale fairly** — popular packages used more in AI suggestions get more
4. **Require minimal overhead** — download stats are already public

This tool gives maintainers the data to make that argument concretely.

---

## License

MIT — see [LICENSE](LICENSE) for details.
