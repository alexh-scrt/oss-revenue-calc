"""Tests for oss_revenue_calc.report module.

Covers terminal report rendering (using Rich's Console capture mode),
JSON export correctness, CSV export correctness, and edge cases such as
empty result lists and missing optional model results.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Optional

import pytest
from rich.console import Console

from oss_revenue_calc.models import (
    ModelResult,
    PackageStats,
    PlatformConfig,
    Registry,
    RevenueModel,
    RevenueResult,
)
from oss_revenue_calc.report import (
    _CSV_FIELDNAMES,
    _model_display_name,
    _result_to_csv_row,
    export_csv,
    export_json,
    render_multi_platform_report,
    render_platforms_table,
    render_terminal_report,
)
from oss_revenue_calc.platforms import get_platform_or_raise, list_platforms


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_stats(
    package_name: str = "requests",
    total_downloads: int = 10_000_000,
    period_days: int = 365,
    registry: Registry = Registry.PYPI,
    description: Optional[str] = "HTTP for Humans.",
    version: Optional[str] = "2.31.0",
    homepage: Optional[str] = "https://requests.readthedocs.io",
) -> PackageStats:
    return PackageStats(
        package_name=package_name,
        registry=registry,
        total_downloads=total_downloads,
        period_days=period_days,
        description=description,
        version=version,
        homepage=homepage,
    )


def _make_platform(
    name: str = "Test Platform",
    slug: str = "test",
    subscribers: int = 1_000_000,
    monthly_arpu: float = 10.0,
    oss_revenue_share: float = 0.05,
) -> PlatformConfig:
    return PlatformConfig(
        name=name,
        slug=slug,
        subscribers=subscribers,
        monthly_arpu=monthly_arpu,
        oss_revenue_share=oss_revenue_share,
    )


def _make_result(
    package_name: str = "requests",
    total_downloads: int = 10_000_000,
    ai_share: float = 0.30,
    with_prorata: bool = True,
    with_peruse: bool = True,
    prorata_annual: float = 12_000.0,
    peruse_annual: float = 8_000.0,
    platform: Optional[PlatformConfig] = None,
    package_download_share: Optional[float] = 0.001,
) -> RevenueResult:
    stats = _make_stats(
        package_name=package_name,
        total_downloads=total_downloads,
    )
    p = platform or _make_platform()
    result = RevenueResult(
        package_stats=stats,
        platform=p,
        ai_share=ai_share,
        package_download_share=package_download_share,
    )
    if with_prorata:
        result.model_results.append(
            ModelResult(
                model=RevenueModel.PRORATA,
                annual_revenue_usd=prorata_annual,
                monthly_revenue_usd=prorata_annual / 12,
                notes="Pro-rata notes.",
            )
        )
    if with_peruse:
        result.model_results.append(
            ModelResult(
                model=RevenueModel.PERUSE,
                annual_revenue_usd=peruse_annual,
                monthly_revenue_usd=peruse_annual / 12,
                notes="Per-use notes.",
            )
        )
    return result


def _capture_console_output(fn, *args, **kwargs) -> str:
    """Run a render function with a captured Rich console and return the output."""
    con = Console(record=True, width=120)
    fn(*args, console=con, **kwargs)
    return con.export_text()


# ---------------------------------------------------------------------------
# _model_display_name tests
# ---------------------------------------------------------------------------

class TestModelDisplayName:
    def test_prorata(self) -> None:
        name = _model_display_name(RevenueModel.PRORATA)
        assert "pro" in name.lower() or "rata" in name.lower() or "spotify" in name.lower()

    def test_peruse(self) -> None:
        name = _model_display_name(RevenueModel.PERUSE)
        assert "use" in name.lower() or "micro" in name.lower() or "per" in name.lower()

    def test_returns_string(self) -> None:
        for model in (RevenueModel.PRORATA, RevenueModel.PERUSE, RevenueModel.BOTH):
            assert isinstance(_model_display_name(model), str)
            assert len(_model_display_name(model)) > 0


# ---------------------------------------------------------------------------
# render_terminal_report tests
# ---------------------------------------------------------------------------

class TestRenderTerminalReport:
    """Tests for the single-platform terminal report renderer."""

    def test_renders_without_error(self) -> None:
        result = _make_result()
        # Should not raise
        _capture_console_output(render_terminal_report, result)

    def test_output_contains_package_name(self) -> None:
        result = _make_result(package_name="requests")
        output = _capture_console_output(render_terminal_report, result)
        assert "requests" in output

    def test_output_contains_total_downloads(self) -> None:
        result = _make_result(total_downloads=10_000_000)
        output = _capture_console_output(render_terminal_report, result)
        # The number should appear, possibly formatted with commas
        assert "10,000,000" in output or "10000000" in output

    def test_output_contains_platform_name(self) -> None:
        platform = _make_platform(name="GitHub Copilot")
        result = _make_result(platform=platform)
        output = _capture_console_output(render_terminal_report, result)
        assert "GitHub Copilot" in output

    def test_output_contains_ai_share_percentage(self) -> None:
        result = _make_result(ai_share=0.30)
        output = _capture_console_output(render_terminal_report, result)
        assert "30.0%" in output or "30%" in output

    def test_output_contains_annual_revenue(self) -> None:
        result = _make_result(prorata_annual=12_450.75)
        output = _capture_console_output(render_terminal_report, result)
        # The dollar amount should appear somewhere
        assert "12,450" in output or "12450" in output

    def test_output_contains_monthly_revenue(self) -> None:
        result = _make_result(prorata_annual=12_000.0)
        output = _capture_console_output(render_terminal_report, result)
        # Monthly = 12000 / 12 = 1000
        assert "1,000" in output or "1000" in output

    def test_output_contains_registry_pypi(self) -> None:
        result = _make_result()
        output = _capture_console_output(render_terminal_report, result)
        assert "PyPI" in output

    def test_output_contains_registry_npm(self) -> None:
        stats = PackageStats(
            package_name="lodash",
            registry=Registry.NPM,
            total_downloads=5_000_000,
            period_days=365,
        )
        platform = _make_platform()
        result = RevenueResult(
            package_stats=stats,
            platform=platform,
            ai_share=0.25,
        )
        result.model_results.append(
            ModelResult(
                model=RevenueModel.PRORATA,
                annual_revenue_usd=5_000.0,
                monthly_revenue_usd=416.67,
            )
        )
        output = _capture_console_output(render_terminal_report, result)
        assert "npm" in output

    def test_output_contains_subscribers(self) -> None:
        platform = _make_platform(subscribers=1_300_000)
        result = _make_result(platform=platform)
        output = _capture_console_output(render_terminal_report, result)
        assert "1,300,000" in output or "1300000" in output

    def test_output_contains_period_days(self) -> None:
        result = _make_result()
        output = _capture_console_output(render_terminal_report, result)
        assert "365" in output

    def test_output_contains_oss_pool(self) -> None:
        platform = _make_platform(
            subscribers=1_000_000,
            monthly_arpu=10.0,
            oss_revenue_share=0.05,
        )
        result = _make_result(platform=platform)
        output = _capture_console_output(render_terminal_report, result)
        # OSS pool = 1_000_000 * 10 * 12 * 0.05 = 6_000_000
        assert "6,000,000" in output or "6000000" in output

    def test_output_shows_both_models_when_present(self) -> None:
        result = _make_result(with_prorata=True, with_peruse=True)
        output = _capture_console_output(render_terminal_report, result)
        # Both model names should appear
        assert any(kw in output.lower() for kw in ("pro", "rata", "spotify"))
        assert any(kw in output.lower() for kw in ("per", "use", "micro"))

    def test_output_shows_average_when_two_models(self) -> None:
        result = _make_result(prorata_annual=10_000.0, peruse_annual=8_000.0)
        output = _capture_console_output(render_terminal_report, result)
        assert "Average" in output or "average" in output

    def test_output_no_average_when_single_model(self) -> None:
        result = _make_result(with_prorata=True, with_peruse=False)
        output = _capture_console_output(render_terminal_report, result)
        # Average row should not appear when only one model
        # (it's added only when > 1 model results)
        assert "Average" not in output

    def test_optional_version_shown_when_present(self) -> None:
        stats = PackageStats(
            package_name="requests",
            registry=Registry.PYPI,
            total_downloads=5_000_000,
            period_days=365,
            version="2.31.0",
        )
        result = RevenueResult(
            package_stats=stats,
            platform=_make_platform(),
            ai_share=0.30,
        )
        output = _capture_console_output(render_terminal_report, result)
        assert "2.31.0" in output

    def test_optional_description_shown_when_present(self) -> None:
        stats = PackageStats(
            package_name="requests",
            registry=Registry.PYPI,
            total_downloads=5_000_000,
            period_days=365,
            description="HTTP for Humans.",
        )
        result = RevenueResult(
            package_stats=stats,
            platform=_make_platform(),
            ai_share=0.30,
        )
        output = _capture_console_output(render_terminal_report, result)
        assert "HTTP for Humans" in output

    def test_long_description_truncated(self) -> None:
        long_desc = "A" * 200
        stats = PackageStats(
            package_name="pkg",
            registry=Registry.PYPI,
            total_downloads=1_000,
            period_days=365,
            description=long_desc,
        )
        result = RevenueResult(
            package_stats=stats,
            platform=_make_platform(),
            ai_share=0.10,
        )
        output = _capture_console_output(render_terminal_report, result)
        # The full 200-char description should NOT appear verbatim
        assert long_desc not in output
        # But some truncated form should be there
        assert "A" * 80 in output or "…" in output or "..." in output

    def test_zero_revenue_renders_without_error(self) -> None:
        result = _make_result(
            total_downloads=0,
            prorata_annual=0.0,
            peruse_annual=0.0,
        )
        output = _capture_console_output(render_terminal_report, result)
        assert "$0.00" in output

    def test_package_download_share_shown(self) -> None:
        result = _make_result(package_download_share=0.00123)
        output = _capture_console_output(render_terminal_report, result)
        # The share percentage should be shown (0.1230%)
        assert "0.12" in output or "0.1230" in output

    def test_real_copilot_platform_renders(self) -> None:
        """End-to-end render with a real platform config."""
        from oss_revenue_calc.calculator import calculate_revenue
        stats = _make_stats(total_downloads=100_000_000)
        copilot = get_platform_or_raise("copilot")
        result = calculate_revenue(stats, copilot, ai_share=0.30)
        output = _capture_console_output(render_terminal_report, result)
        assert "GitHub Copilot" in output
        assert "requests" in output


# ---------------------------------------------------------------------------
# render_multi_platform_report tests
# ---------------------------------------------------------------------------

class TestRenderMultiPlatformReport:
    """Tests for the multi-platform comparison table renderer."""

    def test_renders_without_error(self) -> None:
        results = [_make_result(platform=p) for p in list_platforms()[:3]]
        _capture_console_output(render_multi_platform_report, results)

    def test_empty_results_renders_nothing(self) -> None:
        output = _capture_console_output(render_multi_platform_report, [])
        # Should produce no content (or just whitespace)
        assert output.strip() == ""

    def test_output_contains_package_name(self) -> None:
        results = [_make_result(package_name="numpy")]
        output = _capture_console_output(render_multi_platform_report, results)
        assert "numpy" in output

    def test_output_contains_all_platform_names(self) -> None:
        platforms = list_platforms()
        results = [_make_result(platform=p) for p in platforms]
        output = _capture_console_output(render_multi_platform_report, results)
        for platform in platforms:
            assert platform.name in output, (
                f"Platform name {platform.name!r} not found in multi-platform report"
            )

    def test_output_contains_revenue_values(self) -> None:
        results = [
            _make_result(prorata_annual=15_000.0, peruse_annual=9_000.0)
        ]
        output = _capture_console_output(render_multi_platform_report, results)
        assert "15,000" in output or "15000" in output

    def test_renders_all_built_in_platforms(self) -> None:
        from oss_revenue_calc.calculator import calculate_revenue_for_platforms
        stats = _make_stats(total_downloads=50_000_000)
        platforms = list_platforms()
        results = calculate_revenue_for_platforms(stats, platforms, ai_share=0.30)
        output = _capture_console_output(render_multi_platform_report, results)
        assert "requests" in output
        for p in platforms:
            assert p.name in output


# ---------------------------------------------------------------------------
# render_platforms_table tests
# ---------------------------------------------------------------------------

class TestRenderPlatformsTable:
    """Tests for the platforms list renderer."""

    def test_renders_without_error(self) -> None:
        _capture_console_output(render_platforms_table, list_platforms())

    def test_output_contains_all_platform_names(self) -> None:
        platforms = list_platforms()
        output = _capture_console_output(render_platforms_table, platforms)
        for p in platforms:
            assert p.name in output

    def test_output_contains_all_slugs(self) -> None:
        platforms = list_platforms()
        output = _capture_console_output(render_platforms_table, platforms)
        for p in platforms:
            assert p.slug in output

    def test_output_contains_subscriber_counts(self) -> None:
        platforms = list_platforms()
        output = _capture_console_output(render_platforms_table, platforms)
        # At least the Copilot subscriber count should appear
        assert "1,300,000" in output or "1300000" in output

    def test_output_contains_arpu(self) -> None:
        platforms = list_platforms()
        output = _capture_console_output(render_platforms_table, platforms)
        # Copilot ARPU is $10.00
        assert "10.00" in output or "$10" in output

    def test_empty_platforms_renders_without_error(self) -> None:
        output = _capture_console_output(render_platforms_table, [])
        # Should not raise; may render empty table
        assert isinstance(output, str)


# ---------------------------------------------------------------------------
# export_json tests
# ---------------------------------------------------------------------------

class TestExportJson:
    """Tests for the JSON export function."""

    def test_returns_valid_json_string(self) -> None:
        results = [_make_result()]
        output = export_json(results)
        parsed = json.loads(output)
        assert isinstance(parsed, list)

    def test_single_result_in_list(self) -> None:
        results = [_make_result()]
        parsed = json.loads(export_json(results))
        assert len(parsed) == 1

    def test_multiple_results_in_list(self) -> None:
        results = [_make_result(), _make_result(package_name="numpy")]
        parsed = json.loads(export_json(results))
        assert len(parsed) == 2

    def test_empty_results_gives_empty_array(self) -> None:
        parsed = json.loads(export_json([]))
        assert parsed == []

    def test_output_contains_package_name(self) -> None:
        results = [_make_result(package_name="requests")]
        parsed = json.loads(export_json(results))
        assert parsed[0]["package_name"] == "requests"

    def test_output_contains_registry(self) -> None:
        results = [_make_result()]
        parsed = json.loads(export_json(results))
        assert parsed[0]["registry"] == "pypi"

    def test_output_contains_total_downloads(self) -> None:
        results = [_make_result(total_downloads=5_000_000)]
        parsed = json.loads(export_json(results))
        assert parsed[0]["total_downloads"] == 5_000_000

    def test_output_contains_ai_share(self) -> None:
        results = [_make_result(ai_share=0.35)]
        parsed = json.loads(export_json(results))
        assert parsed[0]["ai_share"] == pytest.approx(0.35)

    def test_output_contains_model_results(self) -> None:
        results = [_make_result(prorata_annual=10_000.0, peruse_annual=7_000.0)]
        parsed = json.loads(export_json(results))
        model_results = parsed[0]["model_results"]
        assert len(model_results) == 2

    def test_model_results_have_correct_keys(self) -> None:
        results = [_make_result()]
        parsed = json.loads(export_json(results))
        for mr in parsed[0]["model_results"]:
            assert "model" in mr
            assert "annual_revenue_usd" in mr
            assert "monthly_revenue_usd" in mr

    def test_model_values_correct(self) -> None:
        results = [_make_result(prorata_annual=12_000.0, peruse_annual=8_000.0)]
        parsed = json.loads(export_json(results))
        model_results = {mr["model"]: mr for mr in parsed[0]["model_results"]}
        assert model_results["prorata"]["annual_revenue_usd"] == pytest.approx(12_000.0)
        assert model_results["peruse"]["annual_revenue_usd"] == pytest.approx(8_000.0)

    def test_platform_fields_present(self) -> None:
        results = [_make_result()]
        parsed = json.loads(export_json(results))
        item = parsed[0]
        assert "platform_name" in item
        assert "platform_slug" in item
        assert "platform_subscribers" in item
        assert "platform_monthly_arpu" in item
        assert "platform_oss_revenue_share" in item
        assert "platform_annual_revenue" in item
        assert "platform_annual_oss_pool" in item

    def test_average_revenue_fields_present(self) -> None:
        results = [_make_result()]
        parsed = json.loads(export_json(results))
        item = parsed[0]
        assert "average_annual_revenue_usd" in item
        assert "average_monthly_revenue_usd" in item

    def test_average_revenue_correct(self) -> None:
        results = [_make_result(prorata_annual=10_000.0, peruse_annual=8_000.0)]
        parsed = json.loads(export_json(results))
        assert parsed[0]["average_annual_revenue_usd"] == pytest.approx(9_000.0)
        assert parsed[0]["average_monthly_revenue_usd"] == pytest.approx(750.0)

    def test_indent_parameter_respected(self) -> None:
        results = [_make_result()]
        output_2 = export_json(results, indent=2)
        output_4 = export_json(results, indent=4)
        # Deeper indent means longer output
        assert len(output_4) > len(output_2)

    def test_output_is_utf8_safe(self) -> None:
        """Non-ASCII package names should be serialised safely."""
        stats = PackageStats(
            package_name="pkg-ünïcödé",
            registry=Registry.PYPI,
            total_downloads=1_000,
            period_days=365,
        )
        result = RevenueResult(
            package_stats=stats,
            platform=_make_platform(),
            ai_share=0.10,
        )
        output = export_json([result])
        parsed = json.loads(output)
        assert parsed[0]["package_name"] == "pkg-ünïcödé"

    def test_real_calculator_result_serialisable(self) -> None:
        """A result from the real calculator should JSON-serialise cleanly."""
        from oss_revenue_calc.calculator import calculate_revenue
        stats = _make_stats()
        copilot = get_platform_or_raise("copilot")
        result = calculate_revenue(stats, copilot, ai_share=0.30)
        output = export_json([result])
        parsed = json.loads(output)
        assert len(parsed) == 1
        assert parsed[0]["platform_slug"] == "copilot"


# ---------------------------------------------------------------------------
# export_csv tests
# ---------------------------------------------------------------------------

class TestExportCsv:
    """Tests for the CSV export function."""

    def test_returns_string(self) -> None:
        results = [_make_result()]
        output = export_csv(results)
        assert isinstance(output, str)

    def test_empty_results_gives_header_only(self) -> None:
        output = export_csv([])
        lines = output.strip().splitlines()
        assert len(lines) == 1  # just the header
        # Header should contain expected columns
        assert "package_name" in lines[0]

    def test_header_contains_expected_columns(self) -> None:
        output = export_csv([_make_result()])
        reader = csv.DictReader(io.StringIO(output))
        assert reader.fieldnames is not None
        for field in _CSV_FIELDNAMES:
            assert field in reader.fieldnames, (
                f"Expected CSV field {field!r} not found in header"
            )

    def test_single_result_produces_one_data_row(self) -> None:
        output = export_csv([_make_result()])
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert len(rows) == 1

    def test_multiple_results_produce_multiple_rows(self) -> None:
        results = [
            _make_result(package_name="requests"),
            _make_result(package_name="numpy"),
            _make_result(package_name="flask"),
        ]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert len(rows) == 3

    def test_package_name_in_csv(self) -> None:
        results = [_make_result(package_name="requests")]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert rows[0]["package_name"] == "requests"

    def test_registry_in_csv(self) -> None:
        results = [_make_result()]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert rows[0]["registry"] == "pypi"

    def test_total_downloads_in_csv(self) -> None:
        results = [_make_result(total_downloads=5_000_000)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert int(rows[0]["total_downloads"]) == 5_000_000

    def test_ai_share_in_csv(self) -> None:
        results = [_make_result(ai_share=0.25)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert float(rows[0]["ai_share"]) == pytest.approx(0.25)

    def test_prorata_annual_in_csv(self) -> None:
        results = [_make_result(prorata_annual=15_000.0)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert float(rows[0]["prorata_annual_usd"]) == pytest.approx(15_000.0)

    def test_peruse_annual_in_csv(self) -> None:
        results = [_make_result(peruse_annual=9_500.0)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert float(rows[0]["peruse_annual_usd"]) == pytest.approx(9_500.0)

    def test_average_annual_in_csv(self) -> None:
        results = [_make_result(prorata_annual=10_000.0, peruse_annual=8_000.0)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert float(rows[0]["average_annual_usd"]) == pytest.approx(9_000.0)

    def test_missing_prorata_gives_empty_string(self) -> None:
        results = [_make_result(with_prorata=False, with_peruse=True)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert rows[0]["prorata_annual_usd"] == ""
        assert rows[0]["prorata_monthly_usd"] == ""

    def test_missing_peruse_gives_empty_string(self) -> None:
        results = [_make_result(with_prorata=True, with_peruse=False)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert rows[0]["peruse_annual_usd"] == ""
        assert rows[0]["peruse_monthly_usd"] == ""

    def test_platform_fields_in_csv(self) -> None:
        platform = _make_platform(name="Test", slug="tst", subscribers=500_000)
        results = [_make_result(platform=platform)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert rows[0]["platform_name"] == "Test"
        assert rows[0]["platform_slug"] == "tst"
        assert int(rows[0]["platform_subscribers"]) == 500_000

    def test_csv_is_parseable_by_stdlib(self) -> None:
        """The CSV output should be parseable by the stdlib csv module."""
        from oss_revenue_calc.calculator import calculate_revenue_for_platforms
        stats = _make_stats()
        platforms = list_platforms()
        results = calculate_revenue_for_platforms(stats, platforms, ai_share=0.30)
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert len(rows) == len(platforms)

    def test_csv_multiple_rows_correct_packages(self) -> None:
        from oss_revenue_calc.calculator import calculate_revenue
        stats = _make_stats(package_name="requests")
        platforms = list_platforms()[:3]
        results = [
            calculate_revenue(stats, p, ai_share=0.30)
            for p in platforms
        ]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        for row in rows:
            assert row["package_name"] == "requests"


# ---------------------------------------------------------------------------
# _result_to_csv_row tests
# ---------------------------------------------------------------------------

class TestResultToCsvRow:
    """Unit tests for the _result_to_csv_row helper."""

    def test_returns_dict(self) -> None:
        result = _make_result()
        row = _result_to_csv_row(result)
        assert isinstance(row, dict)

    def test_all_fieldnames_present(self) -> None:
        result = _make_result()
        row = _result_to_csv_row(result)
        for field in _CSV_FIELDNAMES:
            assert field in row, f"Field {field!r} missing from CSV row"

    def test_package_download_share_none_gives_empty_string(self) -> None:
        stats = _make_stats()
        result = RevenueResult(
            package_stats=stats,
            platform=_make_platform(),
            ai_share=0.30,
            package_download_share=None,
        )
        row = _result_to_csv_row(result)
        assert row["package_download_share"] == ""

    def test_package_download_share_value_rounded(self) -> None:
        stats = _make_stats()
        result = RevenueResult(
            package_stats=stats,
            platform=_make_platform(),
            ai_share=0.30,
            package_download_share=0.001234567890,
        )
        row = _result_to_csv_row(result)
        # Should be rounded to 8 decimal places
        assert isinstance(row["package_download_share"], float)
        assert row["package_download_share"] == pytest.approx(0.00123457, rel=1e-4)
