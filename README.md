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

### Print the installed version

```bash
oss-revenue-calc version
```

---

## Revenue Models

### 1. Spotify-Style Pro-Rata Model

The platform designates a fixed percentage of total subscription revenue as the "OSS pool." Each package receives a share of that pool proportional to its share of total AI-attributed downloads across all packages on the platform.

```
OSS Pool       = Total Platform Revenue × Revenue Share %
Package Share  = AI-Attributed Downloads (package) / AI-Attributed Downloads (all packages)
Package Revenue = OSS Pool × Package Share
```

**Inputs needed:**
- Platform total annual revenue (subscribers × ARPU × 12)
- Platform OSS revenue share percentage
- Package's AI-attributed downloads relative to platform total

### 2. Per-Use Micro-Payment Model

The platform pays a flat micro-payment for each AI-attributed download event, derived from the platform ARPU and the assumed number of download events per subscriber per month.

```
Per-Download Rate   = (Monthly ARPU × OSS Revenue Share %)
                      / Downloads Per Subscriber Per Month
Annual AI Downloads = Total Downloads × AI Share × (365 / Period Days)
Annual Revenue      = Annual AI Downloads × Per-Download Rate
```

**Inputs needed:**
- Package total downloads (fetched automatically)
- AI download share percentage (your estimate)
- Platform ARPU and subscriber count
- Assumed downloads per subscriber per month

---

## Built-In Platforms

| Platform | Subscribers | Monthly ARPU | OSS Share % | Annual OSS Pool |
|----------|------------|--------------|-------------|----------------|
| GitHub Copilot | 1,300,000 | $10.00 | 5% | $7,800,000 |
| Cursor | 300,000 | $20.00 | 5% | $3,600,000 |
| Tabnine | 1,000,000 | $12.00 | 5% | $7,200,000 |
| Amazon CodeWhisperer | 500,000 | $19.00 | 5% | $5,700,000 |
| Sourcegraph Cody | 150,000 | $9.00 | 5% | $810,000 |
| JetBrains AI Assistant | 400,000 | $8.00 | 5% | $1,920,000 |

> **Note:** Subscriber counts and pricing are estimates based on public reporting and may not reflect current figures. Use `--subscribers` and `--arpu` to override with your own research.

---

## Example Output

### Terminal (default)

```
╭─────────────────────────────────────────────────────────────────────────╮
│           OSS Revenue Estimate: requests (PyPI)                         │
╰─────────────────────────────────────────────────────────────────────────╯

📦 Package Stats (last 365 days)
  Registry:                     PyPI
  Package:                      requests
  Latest Version:               2.31.0
  Description:                  HTTP for Humans.
  Total Downloads:              847,234,912
  AI-Attributed:                254,170,474  (30.0% of total)
  Period:                       365 days
  Homepage:                     https://requests.readthedocs.io

🤖 Platform: GitHub Copilot
  Subscribers:                  1,300,000
  Monthly ARPU:                 $10.00
  Annual Revenue:               $156,000,000
  OSS Pool (5%):                $7,800,000
  Source:                       https://github.com/features/copilot

💰 Revenue Estimates
  Model               Annual          Monthly
  ──────────────────────────────────────────────
  Pro-Rata (Spotify)  $12,450.23      $1,037.52
  Per-Use (micro)     $8,322.15       $693.51
  ──────────────────────────────────────────────
  Average             $10,386.19      $865.52

📊 Assumptions
  AI download share:                    30.0%
  Package share of platform downloads:  0.0021%
  Downloads per subscriber per month:   1,200
```

### JSON export (`--output json`)

```json
[
  {
    "package_name": "requests",
    "registry": "pypi",
    "period_days": 365,
    "total_downloads": 847234912,
    "ai_share": 0.3,
    "ai_attributed_downloads": 254170473,
    "package_download_share": 0.000021,
    "platform_name": "GitHub Copilot",
    "platform_slug": "copilot",
    "platform_subscribers": 1300000,
    "platform_monthly_arpu": 10.0,
    "platform_oss_revenue_share": 0.05,
    "platform_annual_revenue": 156000000.0,
    "platform_annual_oss_pool": 7800000.0,
    "model_results": [
      {
        "model": "prorata",
        "annual_revenue_usd": 12450.23,
        "monthly_revenue_usd": 1037.52,
        "notes": "Pro-rata model: ..."
      },
      {
        "model": "peruse",
        "annual_revenue_usd": 8322.15,
        "monthly_revenue_usd": 693.51,
        "notes": "Per-use model: ..."
      }
    ],
    "average_annual_revenue_usd": 10386.19,
    "average_monthly_revenue_usd": 865.52
  }
]
```

### CSV export (`--output csv`)

```csv
package_name,registry,period_days,total_downloads,ai_share,ai_attributed_downloads,package_download_share,platform_name,platform_slug,platform_subscribers,platform_monthly_arpu,platform_oss_revenue_share,platform_annual_revenue,platform_annual_oss_pool,prorata_annual_usd,prorata_monthly_usd,peruse_annual_usd,peruse_monthly_usd,average_annual_usd,average_monthly_usd
requests,pypi,365,847234912,0.3,254170473,2.1e-05,GitHub Copilot,copilot,1300000,10.0,0.05,156000000.0,7800000.0,12450.23,1037.52,8322.15,693.51,10386.19,865.52
```

---

## Multi-Platform Comparison

Run `--all-platforms` to compare revenue estimates across every built-in platform at once:

```bash
oss-revenue-calc calculate requests --all-platforms --ai-share 0.30
```

```
╭─────────────────────────────────────────────────────────────────╮
│        OSS Revenue Comparison: requests (PyPI)                  │
╰─────────────────────────────────────────────────────────────────╯

📦 Package: requests  847,234,912 total downloads (365 days)
🤖 AI Share: 30.0%  (254,170,474 AI-attributed downloads / year)

             Revenue Estimates by Platform
╭────────────────────────┬────────────┬─────────────┬────────────┬────────────┬────────────┬───────────╮
│ Platform               │ Subscribers│ OSS Pool/yr │ Pro-Rata/yr│ Per-Use/yr │ Average/yr │ Average/mo│
├────────────────────────┼────────────┼─────────────┼────────────┼────────────┼────────────┼───────────┤
│ GitHub Copilot         │ 1,300,000  │ $7,800,000  │ $12,450.23 │ $8,322.15  │ $10,386.19 │ $865.52   │
│ Cursor                 │ 300,000    │ $3,600,000  │ $5,742.56  │ $12,708.52 │ $9,225.54  │ $768.80   │
│ Tabnine                │ 1,000,000  │ $7,200,000  │ $8,235.10  │ $8,464.91  │ $8,350.01  │ $695.83   │
│ Amazon CodeWhisperer   │ 500,000    │ $5,700,000  │ $6,515.22  │ $12,012.45 │ $9,263.84  │ $771.99   │
│ Sourcegraph Cody       │ 150,000    │ $810,000    │ $928.12    │ $7,628.11  │ $4,278.12  │ $356.51   │
│ JetBrains AI Assistant │ 400,000    │ $1,920,000  │ $2,198.33  │ $7,552.22  │ $4,875.28  │ $406.27   │
╰────────────────────────┴────────────┴─────────────┴────────────┴────────────┴────────────┴───────────╯
```

---

## CLI Reference

### `oss-revenue-calc calculate <package>`

Calculate revenue estimates for a package.

| Option | Default | Description |
|--------|---------|-------------|
| `--registry` | `pypi` | Package registry (`pypi` or `npm`) |
| `--platform` | `copilot` | Platform preset name or `custom` |
| `--all-platforms` | `False` | Run for all built-in platforms |
| `--ai-share` | `0.30` | Fraction of downloads attributed to AI (0.0–1.0) |
| `--subscribers` | (platform default) | Override subscriber count |
| `--arpu` | (platform default) | Override monthly ARPU in USD |
| `--revenue-share-pct` | (platform default) | Override OSS revenue share fraction (0.0–1.0) |
| `--period` | `365` | Download period in days (30, 90, or 365) |
| `--output` | `terminal` | Output format: `terminal`, `json`, or `csv` |
| `--model` | `both` | Revenue model: `prorata`, `peruse`, or `both` |

### `oss-revenue-calc platforms`

List all built-in platform configurations in a formatted table.

### `oss-revenue-calc version`

Print the installed tool version.

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run a specific test file
pytest tests/test_calculator.py -v

# Run tests matching a pattern
pytest -k "prorata" -v
```

### Project Structure

```
oss_revenue_calc/
├── __init__.py        # Package init and version
├── cli.py             # Typer CLI entry point
├── fetcher.py         # PyPI Stats and npm API fetchers
├── models.py          # Typed dataclasses (PackageStats, PlatformConfig, RevenueResult)
├── calculator.py      # Pro-rata and per-use revenue calculation engine
├── report.py          # Rich terminal output + JSON/CSV export
└── platforms.py       # Built-in platform configurations

tests/
├── test_calculator.py # Revenue model math unit tests
├── test_fetcher.py    # Mocked HTTP fetcher tests
├── test_report.py     # Report formatting and export tests
└── test_models.py     # Data model and platform registry tests
```

---

## Architecture

### Data Flow

```
 CLI input
    │
    ▼
 fetch_package_stats()
    │   PyPI Stats API  /  npm Downloads API
    │   PyPI JSON API   /  npm Registry API
    ▼
 PackageStats
    │
    ├──► calculate_prorata()  ──► ModelResult (prorata)
    │
    ├──► calculate_peruse()   ──► ModelResult (peruse)
    │
    ▼
 RevenueResult
    │
    ├──► render_terminal_report()   (Rich console)
    ├──► export_json()              (stdout)
    └──► export_csv()               (stdout)
```

### Revenue Model Details

#### Pro-Rata Model

Inspired by Spotify's rights-holder payment model. A percentage of the platform's total subscription revenue is pooled for OSS maintainers. Each package's share is proportional to its AI-attributed downloads relative to all packages on the platform:

```python
# Annual OSS pool
oss_pool = subscribers * monthly_arpu * 12 * oss_revenue_share

# Package's share (annualised AI downloads / total platform AI downloads)
package_share = (total_downloads * ai_share * (365 / period_days)) / total_platform_ai_downloads

# Package annual revenue
annual_revenue = oss_pool * package_share
```

When `total_platform_ai_downloads` is not supplied, it is estimated as:
```python
total_platform_ai_downloads = subscribers * downloads_per_subscriber_per_month * 12
```

#### Per-Use Model

A micro-payment rate is derived from the platform's ARPU and an assumed number of download events per subscriber per month:

```python
# Micro-payment rate per AI-attributed download
per_download_rate = (monthly_arpu * oss_revenue_share) / downloads_per_subscriber_per_month

# Annual AI-attributed downloads (annualised)
annual_ai_downloads = total_downloads * ai_share * (365 / period_days)

# Annual revenue
annual_revenue = annual_ai_downloads * per_download_rate
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

## FAQ

**Q: How accurate are the estimates?**

The estimates are illustrative, not authoritative. Download stats are real (fetched live from PyPI Stats and npm APIs), but the AI attribution share (`--ai-share`) is your estimate. Platform subscriber counts and pricing are based on public reporting and may be outdated. Use `--subscribers` and `--arpu` to input the most current figures you can find.

**Q: What does "AI-attributed downloads" mean?**

It's the fraction of a package's downloads you believe are driven by AI coding assistant suggestions. For example, if you think 30% of `requests` downloads happen because an AI tool suggested `import requests`, you'd use `--ai-share 0.30`. This is the most speculative input; reasonable estimates range from 10%–50% for widely-used packages.

**Q: Why does the pro-rata model give lower numbers than I expected?**

The pro-rata model distributes a fixed pool (e.g. 5% of platform revenue) across *all* packages weighted by download share. A package with even 1 billion downloads per year may have a small share of *total platform AI downloads* across hundreds of thousands of packages. The per-use model typically gives higher per-package estimates for very popular packages.

**Q: Can I use this for npm packages?**

Yes — pass `--registry npm` and provide the package name (including scoped packages like `@babel/core`).

**Q: What periods are supported?**

The `--period` option accepts `30`, `90`, or `365` days. These map directly to what the PyPI Stats and npm APIs can provide natively (last month, three months via scaling, or last year).

---

## License

MIT — see [LICENSE](LICENSE) for details.
