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
    """Build a PackageStats instance for testing."""
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
    """Build a PlatformConfig instance for testing."""
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
    registry: Registry = Registry.PYPI,
) -> RevenueResult:
    """Build a RevenueResult instance for testing."""
    stats = _make_stats(
        package_name=package_name,
        total_downloads=total_downloads,
        registry=registry,
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


def _capture(fn, *args, **kwargs) -> str:
    """Run a render function with a captured Rich console and return the text output."""
    con = Console(record=True, width=120)
    fn(*args, console=con, **kwargs)
    return con.export_text()


# ---------------------------------------------------------------------------
# _model_display_name tests
# ---------------------------------------------------------------------------

class TestModelDisplayName:
    """Tests for the _model_display_name helper."""

    def test_prorata_contains_relevant_keyword(self) -> None:
        name = _model_display_name(RevenueModel.PRORATA)
        lower = name.lower()
        assert "pro" in lower or "rata" in lower or "spotify" in lower

    def test_peruse_contains_relevant_keyword(self) -> None:
        name = _model_display_name(RevenueModel.PERUSE)
        lower = name.lower()
        assert "use" in lower or "micro" in lower or "per" in lower

    def test_returns_non_empty_string_for_all_models(self) -> None:
        for model in (RevenueModel.PRORATA, RevenueModel.PERUSE, RevenueModel.BOTH):
            result = _model_display_name(model)
            assert isinstance(result, str)
            assert len(result) > 0

    def test_prorata_and_peruse_names_differ(self) -> None:
        prorata = _model_display_name(RevenueModel.PRORATA)
        peruse = _model_display_name(RevenueModel.PERUSE)
        assert prorata != peruse


# ---------------------------------------------------------------------------
# render_terminal_report tests
# ---------------------------------------------------------------------------

class TestRenderTerminalReport:
    """Tests for the single-platform terminal report renderer."""

    def test_renders_without_error(self) -> None:
        """Rendering should not raise any exception."""
        result = _make_result()
        _capture(render_terminal_report, result)  # Should not raise

    def test_output_contains_package_name(self) -> None:
        result = _make_result(package_name="requests")
        output = _capture(render_terminal_report, result)
        assert "requests" in output

    def test_output_contains_total_downloads(self) -> None:
        result = _make_result(total_downloads=10_000_000)
        output = _capture(render_terminal_report, result)
        # Number should appear, possibly with commas
        assert "10,000,000" in output or "10000000" in output

    def test_output_contains_platform_name(self) -> None:
        platform = _make_platform(name="GitHub Copilot")
        result = _make_result(platform=platform)
        output = _capture(render_terminal_report, result)
        assert "GitHub Copilot" in output

    def test_output_contains_ai_share_percentage(self) -> None:
        result = _make_result(ai_share=0.30)
        output = _capture(render_terminal_report, result)
        assert "30.0%" in output or "30%" in output

    def test_output_contains_prorata_annual_revenue(self) -> None:
        result = _make_result(prorata_annual=12_450.75)
        output = _capture(render_terminal_report, result)
        assert "12,450" in output or "12450" in output

    def test_output_contains_monthly_revenue(self) -> None:
        result = _make_result(prorata_annual=12_000.0)
        output = _capture(render_terminal_report, result)
        # Monthly = 12000 / 12 = 1000
        assert "1,000" in output or "1000" in output

    def test_output_contains_registry_pypi(self) -> None:
        result = _make_result(registry=Registry.PYPI)
        output = _capture(render_terminal_report, result)
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
        output = _capture(render_terminal_report, result)
        assert "npm" in output

    def test_output_contains_subscriber_count(self) -> None:
        platform = _make_platform(subscribers=1_300_000)
        result = _make_result(platform=platform)
        output = _capture(render_terminal_report, result)
        assert "1,300,000" in output or "1300000" in output

    def test_output_contains_period_days(self) -> None:
        result = _make_result()
        output = _capture(render_terminal_report, result)
        assert "365" in output

    def test_output_contains_oss_pool(self) -> None:
        # OSS pool = 1_000_000 * 10 * 12 * 0.05 = 6_000_000
        platform = _make_platform(
            subscribers=1_000_000,
            monthly_arpu=10.0,
            oss_revenue_share=0.05,
        )
        result = _make_result(platform=platform)
        output = _capture(render_terminal_report, result)
        assert "6,000,000" in output or "6000000" in output

    def test_output_contains_both_model_names(self) -> None:
        result = _make_result(with_prorata=True, with_peruse=True)
        output = _capture(render_terminal_report, result)
        lower = output.lower()
        assert any(kw in lower for kw in ("pro", "rata", "spotify"))
        assert any(kw in lower for kw in ("per", "use", "micro"))

    def test_output_shows_average_when_two_models(self) -> None:
        result = _make_result(prorata_annual=10_000.0, peruse_annual=8_000.0)
        output = _capture(render_terminal_report, result)
        assert "Average" in output or "average" in output

    def test_output_no_average_when_single_model(self) -> None:
        result = _make_result(with_prorata=True, with_peruse=False)
        output = _capture(render_terminal_report, result)
        # Average row should not appear when only one model result
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
        output = _capture(render_terminal_report, result)
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
        output = _capture(render_terminal_report, result)
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
        output = _capture(render_terminal_report, result)
        # Full 200-char string should not be present verbatim
        assert long_desc not in output
        # But it should show something truncated
        assert "A" * 10 in output  # At least part of the description appears

    def test_zero_revenue_renders_without_error(self) -> None:
        result = _make_result(
            total_downloads=0,
            prorata_annual=0.0,
            peruse_annual=0.0,
        )
        output = _capture(render_terminal_report, result)
        assert "$0.00" in output

    def test_package_download_share_shown(self) -> None:
        result = _make_result(package_download_share=0.00123)
        output = _capture(render_terminal_report, result)
        # Share displayed as percentage: 0.1230%
        assert "0.12" in output or "0.1230" in output

    def test_no_version_section_when_version_is_none(self) -> None:
        stats = PackageStats(
            package_name="pkg",
            registry=Registry.PYPI,
            total_downloads=1_000,
            period_days=365,
            version=None,
        )
        result = RevenueResult(
            package_stats=stats,
            platform=_make_platform(),
            ai_share=0.20,
        )
        # Should render without error even when version is None
        output = _capture(render_terminal_report, result)
        assert isinstance(output, str)

    def test_arpu_shown_in_platform_section(self) -> None:
        platform = _make_platform(monthly_arpu=19.99)
        result = _make_result(platform=platform)
        output = _capture(render_terminal_report, result)
        assert "19.99" in output

    def test_homepage_shown_when_present(self) -> None:
        stats = PackageStats(
            package_name="requests",
            registry=Registry.PYPI,
            total_downloads=1_000,
            period_days=365,
            homepage="https://requests.readthedocs.io",
        )
        result = RevenueResult(
            package_stats=stats,
            platform=_make_platform(),
            ai_share=0.20,
        )
        output = _capture(render_terminal_report, result)
        assert "requests.readthedocs.io" in output

    def test_real_copilot_platform_renders(self) -> None:
        """End-to-end render with a real platform config."""
        from oss_revenue_calc.calculator import calculate_revenue
        stats = _make_stats(total_downloads=100_000_000)
        copilot = get_platform_or_raise("copilot")
        result = calculate_revenue(stats, copilot, ai_share=0.30)
        output = _capture(render_terminal_report, result)
        assert "GitHub Copilot" in output
        assert "requests" in output

    def test_ai_attributed_downloads_shown(self) -> None:
        """AI-attributed download count should appear in the report."""
        result = _make_result(total_downloads=10_000_000, ai_share=0.30)
        output = _capture(render_terminal_report, result)
        # 10_000_000 * 0.30 = 3_000_000 AI-attributed
        assert "3,000,000" in output or "3000000" in output

    def test_30_day_period_shown(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=30)
        result = RevenueResult(
            package_stats=stats,
            platform=_make_platform(),
            ai_share=0.25,
        )
        result.model_results.append(
            ModelResult(
                model=RevenueModel.PRORATA,
                annual_revenue_usd=5_000.0,
                monthly_revenue_usd=416.67,
            )
        )
        output = _capture(render_terminal_report, result)
        assert "30" in output

    def test_oss_share_percentage_shown(self) -> None:
        platform = _make_platform(oss_revenue_share=0.05)
        result = _make_result(platform=platform)
        output = _capture(render_terminal_report, result)
        assert "5%" in output or "5.0%" in output or "OSS" in output.upper()

    def test_render_with_no_model_results(self) -> None:
        """Rendering with no model results should not crash."""
        result = _make_result(with_prorata=False, with_peruse=False)
        # Should not raise
        output = _capture(render_terminal_report, result)
        assert isinstance(output, str)


# ---------------------------------------------------------------------------
# render_multi_platform_report tests
# ---------------------------------------------------------------------------

class TestRenderMultiPlatformReport:
    """Tests for the multi-platform comparison table renderer."""

    def test_renders_without_error(self) -> None:
        results = [_make_result(platform=p) for p in list_platforms()[:3]]
        _capture(render_multi_platform_report, results)  # Should not raise

    def test_empty_results_produces_no_output(self) -> None:
        output = _capture(render_multi_platform_report, [])
        assert output.strip() == ""

    def test_output_contains_package_name(self) -> None:
        results = [_make_result(package_name="numpy")]
        output = _capture(render_multi_platform_report, results)
        assert "numpy" in output

    def test_output_contains_all_platform_names(self) -> None:
        platforms = list_platforms()
        results = [_make_result(platform=p) for p in platforms]
        output = _capture(render_multi_platform_report, results)
        for platform in platforms:
            assert platform.name in output, (
                f"Platform name {platform.name!r} not found in multi-platform report"
            )

    def test_output_contains_revenue_value(self) -> None:
        results = [_make_result(prorata_annual=15_000.0, peruse_annual=9_000.0)]
        output = _capture(render_multi_platform_report, results)
        assert "15,000" in output or "15000" in output

    def test_renders_all_built_in_platforms(self) -> None:
        from oss_revenue_calc.calculator import calculate_revenue_for_platforms
        stats = _make_stats(total_downloads=50_000_000)
        platforms = list_platforms()
        results = calculate_revenue_for_platforms(stats, platforms, ai_share=0.30)
        output = _capture(render_multi_platform_report, results)
        assert "requests" in output
        for p in platforms:
            assert p.name in output

    def test_output_contains_ai_share_info(self) -> None:
        results = [_make_result(ai_share=0.25)]
        output = _capture(render_multi_platform_report, results)
        assert "25.0%" in output or "25%" in output

    def test_single_result_renders(self) -> None:
        result = _make_result()
        output = _capture(render_multi_platform_report, [result])
        assert "requests" in output

    def test_multiple_platforms_all_appear(self) -> None:
        platform_a = _make_platform(name="Platform Alpha", slug="alpha")
        platform_b = _make_platform(name="Platform Beta", slug="beta")
        results = [
            _make_result(platform=platform_a),
            _make_result(platform=platform_b),
        ]
        output = _capture(render_multi_platform_report, results)
        assert "Platform Alpha" in output
        assert "Platform Beta" in output


# ---------------------------------------------------------------------------
# render_platforms_table tests
# ---------------------------------------------------------------------------

class TestRenderPlatformsTable:
    """Tests for the platforms list renderer."""

    def test_renders_without_error(self) -> None:
        _capture(render_platforms_table, list_platforms())  # Should not raise

    def test_output_contains_all_platform_names(self) -> None:
        platforms = list_platforms()
        output = _capture(render_platforms_table, platforms)
        for p in platforms:
            assert p.name in output

    def test_output_contains_all_slugs(self) -> None:
        platforms = list_platforms()
        output = _capture(render_platforms_table, platforms)
        for p in platforms:
            assert p.slug in output

    def test_output_contains_subscriber_counts(self) -> None:
        platforms = list_platforms()
        output = _capture(render_platforms_table, platforms)
        # Copilot has 1,300,000 subscribers
        assert "1,300,000" in output or "1300000" in output

    def test_output_contains_arpu(self) -> None:
        platforms = list_platforms()
        output = _capture(render_platforms_table, platforms)
        # Copilot ARPU is $10.00
        assert "10.00" in output or "$10" in output

    def test_output_contains_oss_share_percentage(self) -> None:
        platforms = list_platforms()
        output = _capture(render_platforms_table, platforms)
        assert "5.0%" in output or "5%" in output

    def test_empty_platforms_renders_without_error(self) -> None:
        output = _capture(render_platforms_table, [])
        assert isinstance(output, str)

    def test_output_contains_annual_oss_pool_for_copilot(self) -> None:
        copilot = get_platform_or_raise("copilot")
        output = _capture(render_platforms_table, [copilot])
        # Copilot OSS pool = 1_300_000 * 10 * 12 * 0.05 = 7_800_000
        assert "7,800,000" in output or "7800000" in output

    def test_custom_platform_renders(self) -> None:
        from oss_revenue_calc.platforms import build_custom_platform
        custom = build_custom_platform(
            subscribers=500_000,
            monthly_arpu=15.0,
            oss_revenue_share=0.05,
            name="My Custom Platform",
            slug="custom-test",
        )
        output = _capture(render_platforms_table, [custom])
        assert "My Custom Platform" in output
        assert "custom-test" in output


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
        results = [
            _make_result(),
            _make_result(package_name="numpy"),
        ]
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
        results = [_make_result(registry=Registry.PYPI)]
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

    def test_model_results_have_required_keys(self) -> None:
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
        for key in (
            "platform_name",
            "platform_slug",
            "platform_subscribers",
            "platform_monthly_arpu",
            "platform_oss_revenue_share",
            "platform_annual_revenue",
            "platform_annual_oss_pool",
        ):
            assert key in item, f"Expected key {key!r} in JSON output"

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

    def test_indent_parameter_affects_output_length(self) -> None:
        results = [_make_result()]
        output_2 = export_json(results, indent=2)
        output_4 = export_json(results, indent=4)
        assert len(output_4) > len(output_2)

    def test_output_is_utf8_safe(self) -> None:
        """Non-ASCII package names should be serialised correctly."""
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

    def test_ai_attributed_downloads_field_present(self) -> None:
        results = [_make_result(total_downloads=10_000_000, ai_share=0.30)]
        parsed = json.loads(export_json(results))
        assert "ai_attributed_downloads" in parsed[0]
        assert parsed[0]["ai_attributed_downloads"] == 3_000_000

    def test_period_days_field_correct(self) -> None:
        results = [_make_result()]
        parsed = json.loads(export_json(results))
        assert parsed[0]["period_days"] == 365

    def test_npm_registry_in_json(self) -> None:
        result = _make_result(registry=Registry.NPM)
        parsed = json.loads(export_json([result]))
        assert parsed[0]["registry"] == "npm"

    def test_package_download_share_in_json(self) -> None:
        result = _make_result(package_download_share=0.00234)
        parsed = json.loads(export_json([result]))
        assert parsed[0]["package_download_share"] == pytest.approx(0.00234, rel=1e-4)

    def test_package_download_share_none_in_json(self) -> None:
        stats = _make_stats()
        result = RevenueResult(
            package_stats=stats,
            platform=_make_platform(),
            ai_share=0.20,
            package_download_share=None,
        )
        parsed = json.loads(export_json([result]))
        assert parsed[0]["package_download_share"] is None

    def test_model_notes_in_json(self) -> None:
        """Model notes should appear in JSON output."""
        result = _make_result()
        parsed = json.loads(export_json([result]))
        for mr in parsed[0]["model_results"]:
            # Notes field should be present (may be None or a string)
            assert "notes" in mr

    def test_three_results_serialise_correctly(self) -> None:
        results = [
            _make_result(package_name="requests"),
            _make_result(package_name="numpy"),
            _make_result(package_name="flask"),
        ]
        parsed = json.loads(export_json(results))
        names = [item["package_name"] for item in parsed]
        assert "requests" in names
        assert "numpy" in names
        assert "flask" in names


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
        assert len(lines) == 1  # Just the header row
        assert "package_name" in lines[0]

    def test_header_contains_all_expected_columns(self) -> None:
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
        results = [_make_result(registry=Registry.PYPI)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert rows[0]["registry"] == "pypi"

    def test_npm_registry_in_csv(self) -> None:
        results = [_make_result(registry=Registry.NPM)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert rows[0]["registry"] == "npm"

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

    def test_prorata_monthly_in_csv(self) -> None:
        results = [_make_result(prorata_annual=12_000.0)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert float(rows[0]["prorata_monthly_usd"]) == pytest.approx(1_000.0)

    def test_peruse_annual_in_csv(self) -> None:
        results = [_make_result(peruse_annual=9_500.0)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert float(rows[0]["peruse_annual_usd"]) == pytest.approx(9_500.0)

    def test_peruse_monthly_in_csv(self) -> None:
        results = [_make_result(peruse_annual=9_600.0)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert float(rows[0]["peruse_monthly_usd"]) == pytest.approx(800.0)

    def test_average_annual_in_csv(self) -> None:
        results = [_make_result(prorata_annual=10_000.0, peruse_annual=8_000.0)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert float(rows[0]["average_annual_usd"]) == pytest.approx(9_000.0)

    def test_average_monthly_in_csv(self) -> None:
        results = [_make_result(prorata_annual=12_000.0, peruse_annual=6_000.0)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        # average annual = 9000, average monthly = 750
        assert float(rows[0]["average_monthly_usd"]) == pytest.approx(750.0)

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

    def test_platform_arpu_in_csv(self) -> None:
        platform = _make_platform(monthly_arpu=19.99)
        results = [_make_result(platform=platform)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert float(rows[0]["platform_monthly_arpu"]) == pytest.approx(19.99)

    def test_platform_oss_share_in_csv(self) -> None:
        platform = _make_platform(oss_revenue_share=0.07)
        results = [_make_result(platform=platform)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert float(rows[0]["platform_oss_revenue_share"]) == pytest.approx(0.07)

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

    def test_csv_multiple_rows_correct_package(self) -> None:
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

    def test_csv_row_order_matches_results_order(self) -> None:
        """CSV rows appear in the same order as the input results list."""
        results = [
            _make_result(package_name="a"),
            _make_result(package_name="b"),
            _make_result(package_name="c"),
        ]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert rows[0]["package_name"] == "a"
        assert rows[1]["package_name"] == "b"
        assert rows[2]["package_name"] == "c"

    def test_ai_attributed_downloads_in_csv(self) -> None:
        results = [_make_result(total_downloads=10_000_000, ai_share=0.30)]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert int(rows[0]["ai_attributed_downloads"]) == 3_000_000

    def test_period_days_in_csv(self) -> None:
        results = [_make_result()]
        output = export_csv(results)
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert int(rows[0]["period_days"]) == 365

    def test_csv_no_model_results_gives_empty_strings(self) -> None:
        """Result with no model_results gives empty strings for revenue fields."""
        result = _make_result(with_prorata=False, with_peruse=False)
        output = export_csv([result])
        reader = csv.DictReader(io.StringIO(output))
        rows = list(reader)
        assert rows[0]["prorata_annual_usd"] == ""
        assert rows[0]["peruse_annual_usd"] == ""


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

    def test_package_download_share_value_rounded_to_8_places(self) -> None:
        stats = _make_stats()
        result = RevenueResult(
            package_stats=stats,
            platform=_make_platform(),
            ai_share=0.30,
            package_download_share=0.001234567890,
        )
        row = _result_to_csv_row(result)
        assert isinstance(row["package_download_share"], float)
        assert row["package_download_share"] == pytest.approx(0.00123457, rel=1e-4)

    def test_prorata_values_populated(self) -> None:
        result = _make_result(prorata_annual=10_000.0, with_peruse=False)
        row = _result_to_csv_row(result)
        assert row["prorata_annual_usd"] == pytest.approx(10_000.0)
        assert row["prorata_monthly_usd"] == pytest.approx(10_000.0 / 12)

    def test_peruse_values_populated(self) -> None:
        result = _make_result(peruse_annual=6_000.0, with_prorata=False)
        row = _result_to_csv_row(result)
        assert row["peruse_annual_usd"] == pytest.approx(6_000.0)
        assert row["peruse_monthly_usd"] == pytest.approx(6_000.0 / 12)

    def test_prorata_missing_gives_empty_string(self) -> None:
        result = _make_result(with_prorata=False, with_peruse=True)
        row = _result_to_csv_row(result)
        assert row["prorata_annual_usd"] == ""
        assert row["prorata_monthly_usd"] == ""

    def test_peruse_missing_gives_empty_string(self) -> None:
        result = _make_result(with_prorata=True, with_peruse=False)
        row = _result_to_csv_row(result)
        assert row["peruse_annual_usd"] == ""
        assert row["peruse_monthly_usd"] == ""

    def test_average_revenue_computed_correctly(self) -> None:
        result = _make_result(prorata_annual=10_000.0, peruse_annual=6_000.0)
        row = _result_to_csv_row(result)
        assert row["average_annual_usd"] == pytest.approx(8_000.0)
        assert row["average_monthly_usd"] == pytest.approx(8_000.0 / 12)

    def test_platform_annual_revenue_correct(self) -> None:
        # 1_000_000 subscribers * $10 ARPU * 12 = $120_000_000
        platform = _make_platform(
            subscribers=1_000_000,
            monthly_arpu=10.0,
            oss_revenue_share=0.05,
        )
        result = _make_result(platform=platform)
        row = _result_to_csv_row(result)
        assert float(row["platform_annual_revenue"]) == pytest.approx(120_000_000.0)

    def test_platform_annual_oss_pool_correct(self) -> None:
        # 120_000_000 * 0.05 = 6_000_000
        platform = _make_platform(
            subscribers=1_000_000,
            monthly_arpu=10.0,
            oss_revenue_share=0.05,
        )
        result = _make_result(platform=platform)
        row = _result_to_csv_row(result)
        assert float(row["platform_annual_oss_pool"]) == pytest.approx(6_000_000.0)

    def test_package_name_preserved(self) -> None:
        result = _make_result(package_name="scikit-learn")
        row = _result_to_csv_row(result)
        assert row["package_name"] == "scikit-learn"

    def test_registry_value_is_string(self) -> None:
        result = _make_result(registry=Registry.PYPI)
        row = _result_to_csv_row(result)
        assert row["registry"] == "pypi"

        result_npm = _make_result(registry=Registry.NPM)
        row_npm = _result_to_csv_row(result_npm)
        assert row_npm["registry"] == "npm"
