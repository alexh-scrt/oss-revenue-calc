"""Unit tests for oss_revenue_calc.calculator.

Covers edge cases and multiple scenarios for the pro-rata and per-use revenue
models, as well as the multi-platform helper and all internal utility functions.
"""

from __future__ import annotations

import pytest

from oss_revenue_calc.calculator import (
    _annualised_ai_downloads,
    _compute_package_download_share,
    _compute_per_download_rate,
    _estimate_total_platform_ai_downloads,
    _resolve_total_platform_ai_downloads,
    calculate_peruse,
    calculate_prorata,
    calculate_revenue,
    calculate_revenue_for_platforms,
)
from oss_revenue_calc.models import (
    ModelResult,
    PackageStats,
    PlatformConfig,
    Registry,
    RevenueModel,
    RevenueResult,
)
from oss_revenue_calc.platforms import get_platform_or_raise, list_platforms


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_stats(
    package_name: str = "requests",
    total_downloads: int = 1_000_000,
    period_days: int = 365,
    registry: Registry = Registry.PYPI,
) -> PackageStats:
    """Build a minimal PackageStats for testing."""
    return PackageStats(
        package_name=package_name,
        registry=registry,
        total_downloads=total_downloads,
        period_days=period_days,
    )


def _make_platform(
    name: str = "Test Platform",
    slug: str = "test",
    subscribers: int = 1_000_000,
    monthly_arpu: float = 10.0,
    oss_revenue_share: float = 0.05,
    downloads_per_subscriber_per_month: float = 1_000.0,
) -> PlatformConfig:
    """Build a minimal PlatformConfig for testing."""
    return PlatformConfig(
        name=name,
        slug=slug,
        subscribers=subscribers,
        monthly_arpu=monthly_arpu,
        oss_revenue_share=oss_revenue_share,
        downloads_per_subscriber_per_month=downloads_per_subscriber_per_month,
    )


# ---------------------------------------------------------------------------
# _annualised_ai_downloads tests
# ---------------------------------------------------------------------------

class TestAnnualisedAiDownloads:
    """Tests for the _annualised_ai_downloads internal helper."""

    def test_365_day_period_no_scaling(self) -> None:
        stats = _make_stats(total_downloads=1_200_000, period_days=365)
        result = _annualised_ai_downloads(stats, ai_share=0.30)
        assert result == int(1_200_000 * 0.30)

    def test_30_day_period_scales_up(self) -> None:
        stats = _make_stats(total_downloads=100_000, period_days=30)
        # annualised = 100_000 * (365/30) = 1_216_666
        annualised = int(100_000 * (365 / 30))
        result = _annualised_ai_downloads(stats, ai_share=0.50)
        assert result == int(annualised * 0.50)

    def test_90_day_period_scales_up(self) -> None:
        stats = _make_stats(total_downloads=300_000, period_days=90)
        annualised = int(300_000 * (365 / 90))
        result = _annualised_ai_downloads(stats, ai_share=0.25)
        assert result == int(annualised * 0.25)

    def test_zero_ai_share(self) -> None:
        stats = _make_stats(total_downloads=5_000_000, period_days=365)
        assert _annualised_ai_downloads(stats, ai_share=0.0) == 0

    def test_full_ai_share(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        assert _annualised_ai_downloads(stats, ai_share=1.0) == 1_000_000

    def test_zero_total_downloads(self) -> None:
        stats = _make_stats(total_downloads=0, period_days=365)
        assert _annualised_ai_downloads(stats, ai_share=0.50) == 0


# ---------------------------------------------------------------------------
# _compute_per_download_rate tests
# ---------------------------------------------------------------------------

class TestComputePerDownloadRate:
    """Tests for the _compute_per_download_rate internal helper."""

    def test_basic_calculation(self) -> None:
        # rate = (10.0 * 0.05) / 1000 = 0.5 / 1000 = 0.0005
        platform = _make_platform(monthly_arpu=10.0, oss_revenue_share=0.05,
                                   downloads_per_subscriber_per_month=1000.0)
        rate = _compute_per_download_rate(platform)
        assert rate == pytest.approx(0.0005)

    def test_higher_arpu(self) -> None:
        platform = _make_platform(monthly_arpu=20.0, oss_revenue_share=0.05,
                                   downloads_per_subscriber_per_month=1000.0)
        rate = _compute_per_download_rate(platform)
        assert rate == pytest.approx(0.001)

    def test_higher_oss_share(self) -> None:
        platform = _make_platform(monthly_arpu=10.0, oss_revenue_share=0.10,
                                   downloads_per_subscriber_per_month=1000.0)
        rate = _compute_per_download_rate(platform)
        assert rate == pytest.approx(0.001)

    def test_more_downloads_per_subscriber_reduces_rate(self) -> None:
        platform_low = _make_platform(monthly_arpu=10.0, oss_revenue_share=0.05,
                                       downloads_per_subscriber_per_month=500.0)
        platform_high = _make_platform(monthly_arpu=10.0, oss_revenue_share=0.05,
                                        downloads_per_subscriber_per_month=2000.0)
        rate_low = _compute_per_download_rate(platform_low)
        rate_high = _compute_per_download_rate(platform_high)
        assert rate_low > rate_high

    def test_zero_arpu_gives_zero_rate(self) -> None:
        platform = _make_platform(monthly_arpu=0.0, oss_revenue_share=0.05,
                                   downloads_per_subscriber_per_month=1000.0)
        rate = _compute_per_download_rate(platform)
        assert rate == pytest.approx(0.0)

    def test_zero_oss_share_gives_zero_rate(self) -> None:
        platform = _make_platform(monthly_arpu=10.0, oss_revenue_share=0.0,
                                   downloads_per_subscriber_per_month=1000.0)
        rate = _compute_per_download_rate(platform)
        assert rate == pytest.approx(0.0)

    def test_copilot_rate_is_reasonable(self) -> None:
        """Copilot's per-download rate should be a small positive fraction."""
        copilot = get_platform_or_raise("copilot")
        rate = _compute_per_download_rate(copilot)
        assert rate > 0.0
        assert rate < 1.0  # Should be well under $1 per download


# ---------------------------------------------------------------------------
# _estimate_total_platform_ai_downloads tests
# ---------------------------------------------------------------------------

class TestEstimateTotalPlatformAiDownloads:
    """Tests for the _estimate_total_platform_ai_downloads helper."""

    def test_basic_estimate(self) -> None:
        # total = 1_000_000 * 1_000 * 12 = 12_000_000_000
        platform = _make_platform(subscribers=1_000_000,
                                   downloads_per_subscriber_per_month=1_000.0)
        total = _estimate_total_platform_ai_downloads(platform)
        assert total == 12_000_000_000

    def test_zero_subscribers_returns_at_least_one(self) -> None:
        platform = _make_platform(subscribers=0)
        total = _estimate_total_platform_ai_downloads(platform)
        assert total >= 1

    def test_result_is_positive_integer(self) -> None:
        platform = _make_platform(subscribers=500_000,
                                   downloads_per_subscriber_per_month=800.0)
        total = _estimate_total_platform_ai_downloads(platform)
        assert isinstance(total, int)
        assert total > 0

    def test_scales_with_subscribers(self) -> None:
        platform_small = _make_platform(subscribers=100_000)
        platform_large = _make_platform(subscribers=1_000_000)
        assert (_estimate_total_platform_ai_downloads(platform_large)
                > _estimate_total_platform_ai_downloads(platform_small))


# ---------------------------------------------------------------------------
# _resolve_total_platform_ai_downloads tests
# ---------------------------------------------------------------------------

class TestResolveTotalPlatformAiDownloads:
    """Tests for the _resolve_total_platform_ai_downloads helper."""

    def test_uses_provided_value(self) -> None:
        platform = _make_platform()
        result = _resolve_total_platform_ai_downloads(platform, 999_000)
        assert result == 999_000

    def test_none_triggers_estimate(self) -> None:
        platform = _make_platform(subscribers=1_000_000,
                                   downloads_per_subscriber_per_month=1_000.0)
        estimated = _estimate_total_platform_ai_downloads(platform)
        result = _resolve_total_platform_ai_downloads(platform, None)
        assert result == estimated

    def test_provided_value_zero_coerced_to_one(self) -> None:
        platform = _make_platform()
        result = _resolve_total_platform_ai_downloads(platform, 0)
        assert result == 1

    def test_negative_provided_value_coerced_to_one(self) -> None:
        platform = _make_platform()
        result = _resolve_total_platform_ai_downloads(platform, -100)
        assert result == 1


# ---------------------------------------------------------------------------
# _compute_package_download_share tests
# ---------------------------------------------------------------------------

class TestComputePackageDownloadShare:
    """Tests for the _compute_package_download_share helper."""

    def test_basic_share(self) -> None:
        share = _compute_package_download_share(1_000, 10_000)
        assert share == pytest.approx(0.10)

    def test_zero_package_downloads(self) -> None:
        share = _compute_package_download_share(0, 10_000)
        assert share == pytest.approx(0.0)

    def test_full_share_when_equals_total(self) -> None:
        share = _compute_package_download_share(5_000, 5_000)
        assert share == pytest.approx(1.0)

    def test_capped_at_one_when_exceeds_total(self) -> None:
        share = _compute_package_download_share(10_000, 5_000)
        assert share == pytest.approx(1.0)

    def test_zero_total_returns_zero(self) -> None:
        share = _compute_package_download_share(1_000, 0)
        assert share == pytest.approx(0.0)

    def test_share_always_between_zero_and_one(self) -> None:
        for pkg_dl in [0, 100, 1_000, 5_000, 10_000, 50_000]:
            share = _compute_package_download_share(pkg_dl, 10_000)
            assert 0.0 <= share <= 1.0


# ---------------------------------------------------------------------------
# calculate_prorata tests
# ---------------------------------------------------------------------------

class TestCalculateProrata:
    """Tests for the calculate_prorata function."""

    def test_returns_model_result(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform = _make_platform()
        result = calculate_prorata(stats, platform, ai_share=0.30)
        assert isinstance(result, ModelResult)
        assert result.model == RevenueModel.PRORATA

    def test_annual_equals_monthly_times_twelve(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform = _make_platform()
        result = calculate_prorata(stats, platform, ai_share=0.30)
        assert result.annual_revenue_usd == pytest.approx(
            result.monthly_revenue_usd * 12, rel=1e-6
        )

    def test_zero_ai_share_gives_zero_revenue(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform = _make_platform()
        result = calculate_prorata(stats, platform, ai_share=0.0)
        assert result.annual_revenue_usd == pytest.approx(0.0)
        assert result.monthly_revenue_usd == pytest.approx(0.0)

    def test_zero_downloads_gives_zero_revenue(self) -> None:
        stats = _make_stats(total_downloads=0, period_days=365)
        platform = _make_platform()
        result = calculate_prorata(stats, platform, ai_share=0.30)
        assert result.annual_revenue_usd == pytest.approx(0.0)

    def test_zero_oss_share_gives_zero_revenue(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform = _make_platform(oss_revenue_share=0.0)
        result = calculate_prorata(stats, platform, ai_share=0.30)
        assert result.annual_revenue_usd == pytest.approx(0.0)

    def test_explicit_total_platform_downloads(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform = _make_platform(
            subscribers=1_000_000,
            monthly_arpu=10.0,
            oss_revenue_share=0.05,
        )
        # ai downloads = 1_000_000 * 0.30 = 300_000
        # total = 10_000_000
        # share = 300_000 / 10_000_000 = 0.03
        # oss pool = 1_000_000 * 10.0 * 12 * 0.05 = 6_000_000
        # annual = 6_000_000 * 0.03 = 180_000
        total = 10_000_000
        result = calculate_prorata(
            stats, platform, ai_share=0.30, total_platform_ai_downloads=total
        )
        assert result.annual_revenue_usd == pytest.approx(180_000.0)

    def test_higher_ai_share_increases_revenue(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform = _make_platform()
        total = 10_000_000
        result_low = calculate_prorata(
            stats, platform, ai_share=0.10, total_platform_ai_downloads=total
        )
        result_high = calculate_prorata(
            stats, platform, ai_share=0.50, total_platform_ai_downloads=total
        )
        assert result_high.annual_revenue_usd > result_low.annual_revenue_usd

    def test_larger_oss_pool_increases_revenue(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform_small = _make_platform(oss_revenue_share=0.02)
        platform_large = _make_platform(oss_revenue_share=0.10)
        total = 10_000_000
        result_small = calculate_prorata(
            stats, platform_small, ai_share=0.30,
            total_platform_ai_downloads=total
        )
        result_large = calculate_prorata(
            stats, platform_large, ai_share=0.30,
            total_platform_ai_downloads=total
        )
        assert result_large.annual_revenue_usd > result_small.annual_revenue_usd

    def test_invalid_ai_share_raises(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        with pytest.raises(ValueError, match="ai_share"):
            calculate_prorata(stats, platform, ai_share=1.5)
        with pytest.raises(ValueError, match="ai_share"):
            calculate_prorata(stats, platform, ai_share=-0.1)

    def test_notes_field_populated(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform = _make_platform()
        result = calculate_prorata(stats, platform, ai_share=0.30)
        assert result.notes is not None
        assert len(result.notes) > 0

    def test_revenue_is_non_negative(self) -> None:
        stats = _make_stats(total_downloads=1_000, period_days=30)
        platform = _make_platform()
        result = calculate_prorata(stats, platform, ai_share=0.01)
        assert result.annual_revenue_usd >= 0.0
        assert result.monthly_revenue_usd >= 0.0

    def test_capped_share_never_exceeds_oss_pool(self) -> None:
        """Package revenue should never exceed the total OSS pool."""
        stats = _make_stats(total_downloads=1_000_000_000, period_days=365)
        platform = _make_platform(
            subscribers=100,
            monthly_arpu=10.0,
            oss_revenue_share=0.05,
            downloads_per_subscriber_per_month=1.0,
        )
        result = calculate_prorata(stats, platform, ai_share=1.0)
        assert result.annual_revenue_usd <= platform.annual_oss_pool + 1e-6

    def test_30_day_period_scaled_correctly(self) -> None:
        """30-day downloads are annualised before computing share."""
        monthly_downloads = 100_000
        stats_30 = _make_stats(total_downloads=monthly_downloads, period_days=30)
        stats_365 = _make_stats(
            total_downloads=int(monthly_downloads * (365 / 30)), period_days=365
        )
        platform = _make_platform()
        total = 12_000_000
        result_30 = calculate_prorata(
            stats_30, platform, ai_share=0.30, total_platform_ai_downloads=total
        )
        result_365 = calculate_prorata(
            stats_365, platform, ai_share=0.30, total_platform_ai_downloads=total
        )
        # Both should give approximately the same annual revenue
        assert result_30.annual_revenue_usd == pytest.approx(
            result_365.annual_revenue_usd, rel=0.01
        )

    def test_copilot_prorata_is_positive(self) -> None:
        """Real Copilot config produces positive revenue for a popular package."""
        stats = _make_stats(total_downloads=100_000_000, period_days=365)
        copilot = get_platform_or_raise("copilot")
        result = calculate_prorata(stats, copilot, ai_share=0.30)
        assert result.annual_revenue_usd > 0.0


# ---------------------------------------------------------------------------
# calculate_peruse tests
# ---------------------------------------------------------------------------

class TestCalculatePeruse:
    """Tests for the calculate_peruse function."""

    def test_returns_model_result(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_peruse(stats, platform, ai_share=0.30)
        assert isinstance(result, ModelResult)
        assert result.model == RevenueModel.PERUSE

    def test_annual_equals_monthly_times_twelve(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_peruse(stats, platform, ai_share=0.30)
        assert result.annual_revenue_usd == pytest.approx(
            result.monthly_revenue_usd * 12, rel=1e-6
        )

    def test_zero_ai_share_gives_zero_revenue(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform = _make_platform()
        result = calculate_peruse(stats, platform, ai_share=0.0)
        assert result.annual_revenue_usd == pytest.approx(0.0)

    def test_zero_downloads_gives_zero_revenue(self) -> None:
        stats = _make_stats(total_downloads=0, period_days=365)
        platform = _make_platform()
        result = calculate_peruse(stats, platform, ai_share=0.30)
        assert result.annual_revenue_usd == pytest.approx(0.0)

    def test_zero_oss_share_gives_zero_revenue(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform = _make_platform(oss_revenue_share=0.0)
        result = calculate_peruse(stats, platform, ai_share=0.30)
        assert result.annual_revenue_usd == pytest.approx(0.0)

    def test_manual_calculation(self) -> None:
        """Verify the per-use formula matches manual arithmetic."""
        total_downloads = 12_000_000  # 365-day period
        ai_share = 0.30
        monthly_arpu = 10.0
        oss_share = 0.05
        dps = 1_000.0

        stats = _make_stats(total_downloads=total_downloads, period_days=365)
        platform = _make_platform(
            monthly_arpu=monthly_arpu,
            oss_revenue_share=oss_share,
            downloads_per_subscriber_per_month=dps,
        )

        # per_download_rate = (10 * 0.05) / 1000 = 0.0005
        per_download_rate = (monthly_arpu * oss_share) / dps
        # annual_ai_downloads = 12_000_000 * 0.30 = 3_600_000
        annual_ai = int(total_downloads * ai_share)
        expected_annual = annual_ai * per_download_rate

        result = calculate_peruse(stats, platform, ai_share=ai_share)
        assert result.annual_revenue_usd == pytest.approx(expected_annual)

    def test_higher_ai_share_increases_revenue(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform = _make_platform()
        result_low = calculate_peruse(stats, platform, ai_share=0.10)
        result_high = calculate_peruse(stats, platform, ai_share=0.50)
        assert result_high.annual_revenue_usd > result_low.annual_revenue_usd

    def test_more_downloads_increases_revenue(self) -> None:
        stats_small = _make_stats(total_downloads=100_000, period_days=365)
        stats_large = _make_stats(total_downloads=10_000_000, period_days=365)
        platform = _make_platform()
        result_small = calculate_peruse(stats_small, platform, ai_share=0.30)
        result_large = calculate_peruse(stats_large, platform, ai_share=0.30)
        assert result_large.annual_revenue_usd > result_small.annual_revenue_usd

    def test_higher_arpu_increases_revenue(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform_low = _make_platform(monthly_arpu=5.0)
        platform_high = _make_platform(monthly_arpu=20.0)
        result_low = calculate_peruse(stats, platform_low, ai_share=0.30)
        result_high = calculate_peruse(stats, platform_high, ai_share=0.30)
        assert result_high.annual_revenue_usd > result_low.annual_revenue_usd

    def test_higher_dps_decreases_revenue(self) -> None:
        """More assumed downloads per subscriber → lower per-download rate."""
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform_low_dps = _make_platform(downloads_per_subscriber_per_month=500.0)
        platform_high_dps = _make_platform(downloads_per_subscriber_per_month=5_000.0)
        result_low = calculate_peruse(stats, platform_low_dps, ai_share=0.30)
        result_high = calculate_peruse(stats, platform_high_dps, ai_share=0.30)
        assert result_low.annual_revenue_usd > result_high.annual_revenue_usd

    def test_invalid_ai_share_raises(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        with pytest.raises(ValueError, match="ai_share"):
            calculate_peruse(stats, platform, ai_share=1.5)
        with pytest.raises(ValueError, match="ai_share"):
            calculate_peruse(stats, platform, ai_share=-0.1)

    def test_notes_field_populated(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_peruse(stats, platform, ai_share=0.30)
        assert result.notes is not None
        assert len(result.notes) > 0

    def test_30_day_period_scaled_correctly(self) -> None:
        """30-day downloads are annualised before computing per-use revenue."""
        monthly_downloads = 100_000
        stats_30 = _make_stats(total_downloads=monthly_downloads, period_days=30)
        annual_equivalent = int(monthly_downloads * (365 / 30))
        stats_365 = _make_stats(total_downloads=annual_equivalent, period_days=365)
        platform = _make_platform()
        result_30 = calculate_peruse(stats_30, platform, ai_share=0.30)
        result_365 = calculate_peruse(stats_365, platform, ai_share=0.30)
        assert result_30.annual_revenue_usd == pytest.approx(
            result_365.annual_revenue_usd, rel=0.01
        )

    def test_revenue_is_non_negative(self) -> None:
        stats = _make_stats(total_downloads=1, period_days=30)
        platform = _make_platform()
        result = calculate_peruse(stats, platform, ai_share=0.01)
        assert result.annual_revenue_usd >= 0.0

    def test_copilot_peruse_is_positive(self) -> None:
        """Real Copilot config produces positive revenue for a popular package."""
        stats = _make_stats(total_downloads=100_000_000, period_days=365)
        copilot = get_platform_or_raise("copilot")
        result = calculate_peruse(stats, copilot, ai_share=0.30)
        assert result.annual_revenue_usd > 0.0


# ---------------------------------------------------------------------------
# calculate_revenue tests
# ---------------------------------------------------------------------------

class TestCalculateRevenue:
    """Tests for the primary calculate_revenue entry point."""

    def test_returns_revenue_result(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.30)
        assert isinstance(result, RevenueResult)

    def test_both_models_by_default(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.30)
        assert len(result.model_results) == 2
        models = {r.model for r in result.model_results}
        assert RevenueModel.PRORATA in models
        assert RevenueModel.PERUSE in models

    def test_prorata_only(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_revenue(
            stats, platform, ai_share=0.30, model=RevenueModel.PRORATA
        )
        assert len(result.model_results) == 1
        assert result.model_results[0].model == RevenueModel.PRORATA

    def test_peruse_only(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_revenue(
            stats, platform, ai_share=0.30, model=RevenueModel.PERUSE
        )
        assert len(result.model_results) == 1
        assert result.model_results[0].model == RevenueModel.PERUSE

    def test_package_stats_preserved(self) -> None:
        stats = _make_stats(package_name="numpy", total_downloads=500_000_000)
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.30)
        assert result.package_stats is stats

    def test_platform_preserved(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.30)
        assert result.platform is platform

    def test_ai_share_preserved(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.42)
        assert result.ai_share == pytest.approx(0.42)

    def test_package_download_share_set(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.30)
        assert result.package_download_share is not None
        assert 0.0 <= result.package_download_share <= 1.0

    def test_package_download_share_zero_with_no_downloads(self) -> None:
        stats = _make_stats(total_downloads=0)
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.30)
        assert result.package_download_share == pytest.approx(0.0)

    def test_invalid_ai_share_raises(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        with pytest.raises(ValueError, match="ai_share"):
            calculate_revenue(stats, platform, ai_share=-0.1)
        with pytest.raises(ValueError, match="ai_share"):
            calculate_revenue(stats, platform, ai_share=1.01)

    def test_explicit_total_platform_downloads(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform = _make_platform(
            subscribers=1_000_000,
            monthly_arpu=10.0,
            oss_revenue_share=0.05,
        )
        total = 10_000_000
        result = calculate_revenue(
            stats, platform, ai_share=0.30,
            total_platform_ai_downloads=total,
            model=RevenueModel.PRORATA,
        )
        prorata = result.get_model_result(RevenueModel.PRORATA)
        assert prorata is not None
        assert prorata.annual_revenue_usd == pytest.approx(180_000.0)

    def test_average_revenue_with_both_models(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.30)
        assert result.average_annual_revenue >= 0.0
        assert result.average_monthly_revenue >= 0.0

    def test_get_model_result_prorata(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.30)
        prorata = result.get_model_result(RevenueModel.PRORATA)
        assert prorata is not None
        assert prorata.model == RevenueModel.PRORATA

    def test_get_model_result_peruse(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.30)
        peruse = result.get_model_result(RevenueModel.PERUSE)
        assert peruse is not None
        assert peruse.model == RevenueModel.PERUSE

    def test_zero_ai_share_both_models_zero(self) -> None:
        stats = _make_stats(total_downloads=1_000_000)
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.0)
        for model_result in result.model_results:
            assert model_result.annual_revenue_usd == pytest.approx(0.0)

    def test_all_built_in_platforms_produce_positive_revenue(self) -> None:
        """All built-in platforms should produce positive revenue for a popular pkg."""
        stats = _make_stats(total_downloads=100_000_000, period_days=365)
        for platform in list_platforms():
            result = calculate_revenue(stats, platform, ai_share=0.30)
            assert result.average_annual_revenue > 0.0, (
                f"Platform {platform.slug} produced zero/negative revenue"
            )

    def test_to_dict_serialisable(self) -> None:
        """Result can be serialised to a dictionary without errors."""
        import json
        stats = _make_stats()
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.30)
        d = result.to_dict()
        # Should be JSON-serialisable
        json_str = json.dumps(d)
        assert len(json_str) > 0

    def test_boundary_ai_share_zero(self) -> None:
        stats = _make_stats(total_downloads=1_000_000)
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=0.0)
        assert result.ai_attributed_downloads == 0

    def test_boundary_ai_share_one(self) -> None:
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        platform = _make_platform()
        result = calculate_revenue(stats, platform, ai_share=1.0)
        assert result.ai_attributed_downloads == 1_000_000


# ---------------------------------------------------------------------------
# calculate_revenue_for_platforms tests
# ---------------------------------------------------------------------------

class TestCalculateRevenueForPlatforms:
    """Tests for the multi-platform helper."""

    def test_returns_one_result_per_platform(self) -> None:
        stats = _make_stats()
        platforms = [_make_platform(slug=f"p{i}", name=f"Platform {i}") for i in range(3)]
        results = calculate_revenue_for_platforms(stats, platforms, ai_share=0.30)
        assert len(results) == 3

    def test_empty_platforms_list(self) -> None:
        stats = _make_stats()
        results = calculate_revenue_for_platforms(stats, [], ai_share=0.30)
        assert results == []

    def test_each_result_has_correct_platform(self) -> None:
        stats = _make_stats()
        platform_a = _make_platform(slug="a", name="A")
        platform_b = _make_platform(slug="b", name="B")
        results = calculate_revenue_for_platforms(
            stats, [platform_a, platform_b], ai_share=0.30
        )
        assert results[0].platform.slug == "a"
        assert results[1].platform.slug == "b"

    def test_all_built_in_platforms(self) -> None:
        stats = _make_stats(total_downloads=50_000_000, period_days=365)
        platforms = list_platforms()
        results = calculate_revenue_for_platforms(stats, platforms, ai_share=0.25)
        assert len(results) == len(platforms)
        for result in results:
            assert result.average_annual_revenue >= 0.0

    def test_invalid_ai_share_raises(self) -> None:
        stats = _make_stats()
        platform = _make_platform()
        with pytest.raises(ValueError, match="ai_share"):
            calculate_revenue_for_platforms([stats], [platform], ai_share=2.0)  # type: ignore

    def test_prorata_only_model(self) -> None:
        stats = _make_stats()
        platforms = [_make_platform(slug="x", name="X")]
        results = calculate_revenue_for_platforms(
            stats, platforms, ai_share=0.30, model=RevenueModel.PRORATA
        )
        assert len(results[0].model_results) == 1
        assert results[0].model_results[0].model == RevenueModel.PRORATA

    def test_order_preserved(self) -> None:
        """Results are returned in the same order as the input platforms."""
        stats = _make_stats()
        platforms = list_platforms()
        results = calculate_revenue_for_platforms(stats, platforms, ai_share=0.20)
        for i, (platform, result) in enumerate(zip(platforms, results)):
            assert result.platform.slug == platform.slug, (
                f"Order mismatch at index {i}: expected {platform.slug}, "
                f"got {result.platform.slug}"
            )

    def test_results_are_independent(self) -> None:
        """Each platform result should differ when platforms differ."""
        stats = _make_stats(total_downloads=1_000_000, period_days=365)
        copilot = get_platform_or_raise("copilot")
        cursor = get_platform_or_raise("cursor")
        results = calculate_revenue_for_platforms(
            stats, [copilot, cursor], ai_share=0.30
        )
        # Copilot and Cursor have different configs, so revenues should differ
        assert results[0].average_annual_revenue != results[1].average_annual_revenue


# ---------------------------------------------------------------------------
# Numerical precision and regression tests
# ---------------------------------------------------------------------------

class TestNumericalPrecision:
    """Regression tests for specific known-value calculations."""

    def test_prorata_known_value(self) -> None:
        """Verify pro-rata output for a fully specified scenario."""
        # Setup:
        #   total_downloads = 10_000_000 (365-day)
        #   ai_share = 0.30  →  ai_downloads = 3_000_000
        #   total_platform_ai = 1_000_000_000
        #   package_share = 3_000_000 / 1_000_000_000 = 0.003
        #   subscribers = 1_000_000, arpu = 10, oss_share = 0.05
        #   annual_revenue = 1_000_000 * 10 * 12 = 120_000_000
        #   oss_pool = 120_000_000 * 0.05 = 6_000_000
        #   package_annual = 6_000_000 * 0.003 = 18_000
        stats = _make_stats(total_downloads=10_000_000, period_days=365)
        platform = _make_platform(
            subscribers=1_000_000,
            monthly_arpu=10.0,
            oss_revenue_share=0.05,
        )
        result = calculate_prorata(
            stats, platform,
            ai_share=0.30,
            total_platform_ai_downloads=1_000_000_000,
        )
        assert result.annual_revenue_usd == pytest.approx(18_000.0)
        assert result.monthly_revenue_usd == pytest.approx(1_500.0)

    def test_peruse_known_value(self) -> None:
        """Verify per-use output for a fully specified scenario."""
        # Setup:
        #   total_downloads = 12_000_000 (365-day)
        #   ai_share = 0.25  →  annual_ai = 3_000_000
        #   monthly_arpu = 10, oss_share = 0.05, dps = 1000
        #   per_download_rate = (10 * 0.05) / 1000 = 0.0005
        #   annual_revenue = 3_000_000 * 0.0005 = 1_500
        stats = _make_stats(total_downloads=12_000_000, period_days=365)
        platform = _make_platform(
            monthly_arpu=10.0,
            oss_revenue_share=0.05,
            downloads_per_subscriber_per_month=1_000.0,
        )
        result = calculate_peruse(stats, platform, ai_share=0.25)
        assert result.annual_revenue_usd == pytest.approx(1_500.0)
        assert result.monthly_revenue_usd == pytest.approx(125.0)

    def test_prorata_single_package_gets_full_pool(self) -> None:
        """If a package has all platform downloads, it gets 100% of the pool."""
        total = 1_000_000
        stats = _make_stats(total_downloads=total, period_days=365)
        platform = _make_platform(
            subscribers=100_000,
            monthly_arpu=10.0,
            oss_revenue_share=0.05,
        )
        # If total_platform_ai_downloads equals the package's AI downloads,
        # the package gets all of the OSS pool.
        ai_downloads = int(total * 0.30)
        result = calculate_prorata(
            stats, platform,
            ai_share=0.30,
            total_platform_ai_downloads=ai_downloads,
        )
        assert result.annual_revenue_usd == pytest.approx(
            platform.annual_oss_pool, rel=1e-6
        )

    def test_prorata_tiny_share_still_positive(self) -> None:
        """Even a package with 0.001% share should get a positive (tiny) amount."""
        stats = _make_stats(total_downloads=1_000, period_days=365)
        platform = _make_platform()
        total = 1_000_000_000_000  # 1 trillion
        result = calculate_prorata(
            stats, platform, ai_share=0.30,
            total_platform_ai_downloads=total,
        )
        # Revenue should be tiny but positive
        assert result.annual_revenue_usd >= 0.0

    def test_peruse_exact_rate_for_copilot(self) -> None:
        """Compute and verify the per-download rate for Copilot."""
        copilot = get_platform_or_raise("copilot")
        # rate = (10.0 * 0.05) / 1200 ≈ 0.000417
        expected_rate = (10.0 * 0.05) / 1200.0
        actual_rate = _compute_per_download_rate(copilot)
        assert actual_rate == pytest.approx(expected_rate)
