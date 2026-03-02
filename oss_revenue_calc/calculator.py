"""Revenue calculation engine for oss_revenue_calc.

Implements the Spotify-style pro-rata and per-use revenue models that consume
:class:`~oss_revenue_calc.models.PackageStats` and
:class:`~oss_revenue_calc.models.PlatformConfig` objects and produce typed
:class:`~oss_revenue_calc.models.RevenueResult` instances.

Revenue Models
--------------

**Pro-Rata (Spotify-style)**
    The platform designates a fixed percentage of its total subscription revenue
    as the "OSS pool". Each package receives a share of that pool proportional
    to its share of total AI-attributed downloads across all packages using the
    platform::

        OSS Pool            = Annual Platform Revenue × OSS Revenue Share %
        Package AI Downloads = Total Downloads × AI Share
        Package Share        = Package AI Downloads / Total Platform AI Downloads
        Package Revenue      = OSS Pool × Package Share

    When the total platform AI download count is unknown, a configurable
    ``total_platform_ai_downloads`` estimate is used.  If that is also absent,
    the function derives a reasonable default from the platform's subscriber
    count and ``downloads_per_subscriber_per_month``.

**Per-Use (micro-payment)**
    The platform pays a flat micro-payment per AI-attributed download, derived
    from the platform ARPU and the assumed number of download events per
    subscriber per month::

        Per-Download Rate = (Monthly ARPU × OSS Revenue Share %) /
                            Downloads Per Subscriber Per Month
        Annual AI Downloads = Total Downloads × AI Share × (365 / Period Days)
        Annual Revenue      = Annual AI Downloads × Per-Download Rate × 12

Example usage::

    from oss_revenue_calc.calculator import calculate_revenue, calculate_prorata, calculate_peruse
    from oss_revenue_calc.models import PackageStats, Registry, RevenueModel
    from oss_revenue_calc.platforms import get_platform_or_raise

    stats = PackageStats(
        package_name="requests",
        registry=Registry.PYPI,
        total_downloads=847_234_912,
        period_days=365,
    )
    platform = get_platform_or_raise("copilot")
    result = calculate_revenue(stats, platform, ai_share=0.30)
    print(result.average_annual_revenue)
"""

from __future__ import annotations

import logging
from typing import Optional

from oss_revenue_calc.models import (
    ModelResult,
    PackageStats,
    PlatformConfig,
    RevenueModel,
    RevenueResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Fallback total number of distinct packages assumed to be "active" on a
#: typical AI coding platform.  Used when ``total_platform_ai_downloads`` is
#: not supplied and cannot be derived from the platform config.
_DEFAULT_ACTIVE_PACKAGE_COUNT: int = 100_000


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_revenue(
    package_stats: PackageStats,
    platform: PlatformConfig,
    ai_share: float,
    model: RevenueModel = RevenueModel.BOTH,
    total_platform_ai_downloads: Optional[int] = None,
) -> RevenueResult:
    """Calculate revenue estimates for a package against a single platform.

    This is the primary entry point for the calculation engine.  It dispatches
    to the individual model calculators based on the ``model`` parameter and
    assembles a :class:`~oss_revenue_calc.models.RevenueResult`.

    Args:
        package_stats: Fetched download statistics for the target package.
        platform: Platform configuration including subscriber count, ARPU, and
            OSS revenue share fraction.
        ai_share: Fraction of total downloads attributed to AI-assisted coding
            (0.0 to 1.0).  For example, ``0.30`` means 30 % of downloads are
            assumed to originate from AI platform suggestions.
        model: Which revenue model(s) to compute.  Defaults to
            :attr:`~oss_revenue_calc.models.RevenueModel.BOTH`.
        total_platform_ai_downloads: Optional estimate of the *total* number of
            AI-attributed downloads across *all* packages on this platform per
            year.  Used by the pro-rata model to calculate the package's share
            of the OSS pool.  When ``None``, an internal estimate is derived
            from the platform's subscriber count and
            ``downloads_per_subscriber_per_month``.

    Returns:
        A populated :class:`~oss_revenue_calc.models.RevenueResult` with model
        results for each requested model.

    Raises:
        ValueError: If ``ai_share`` is outside [0.0, 1.0] or if ``model`` is
            not a valid :class:`~oss_revenue_calc.models.RevenueModel` member.

    Example::

        result = calculate_revenue(stats, platform, ai_share=0.30)
        print(f"Annual estimate: ${result.average_annual_revenue:,.2f}")
    """
    if not 0.0 <= ai_share <= 1.0:
        raise ValueError(
            f"ai_share must be between 0.0 and 1.0, got {ai_share}"
        )

    # Derive total platform AI downloads if not provided
    effective_total = _resolve_total_platform_ai_downloads(
        platform, total_platform_ai_downloads
    )

    # Compute the package's share of total platform AI downloads
    package_ai_downloads_annual = _annualised_ai_downloads(package_stats, ai_share)
    package_download_share = _compute_package_download_share(
        package_ai_downloads_annual, effective_total
    )

    model_results: list[ModelResult] = []

    if model in (RevenueModel.PRORATA, RevenueModel.BOTH):
        prorata_result = calculate_prorata(
            package_stats=package_stats,
            platform=platform,
            ai_share=ai_share,
            total_platform_ai_downloads=effective_total,
        )
        model_results.append(prorata_result)

    if model in (RevenueModel.PERUSE, RevenueModel.BOTH):
        peruse_result = calculate_peruse(
            package_stats=package_stats,
            platform=platform,
            ai_share=ai_share,
        )
        model_results.append(peruse_result)

    result = RevenueResult(
        package_stats=package_stats,
        platform=platform,
        ai_share=ai_share,
        model_results=model_results,
        package_download_share=package_download_share,
    )

    logger.debug(
        "calculate_revenue: package=%s platform=%s ai_share=%.3f "
        "package_download_share=%.6f average_annual=$%.2f",
        package_stats.package_name,
        platform.slug,
        ai_share,
        package_download_share or 0.0,
        result.average_annual_revenue,
    )

    return result


def calculate_prorata(
    package_stats: PackageStats,
    platform: PlatformConfig,
    ai_share: float,
    total_platform_ai_downloads: Optional[int] = None,
) -> ModelResult:
    """Compute a Spotify-style pro-rata revenue estimate.

    The platform's annual OSS pool is distributed proportionally across all
    packages based on each package's share of total AI-attributed annual
    downloads on that platform.

    Formula::

        annual_oss_pool = platform.annual_revenue × platform.oss_revenue_share
        package_ai_downloads = total_downloads × ai_share × (365 / period_days)
        package_share = package_ai_downloads / total_platform_ai_downloads
        annual_revenue = annual_oss_pool × package_share

    Args:
        package_stats: Download statistics for the package.
        platform: Platform configuration.
        ai_share: Fraction of downloads attributed to AI (0.0–1.0).
        total_platform_ai_downloads: Total AI-attributed annual downloads across
            all packages on the platform.  When ``None``, estimated internally
            from the platform config.

    Returns:
        A :class:`~oss_revenue_calc.models.ModelResult` for the pro-rata model.

    Raises:
        ValueError: If ``ai_share`` is outside [0.0, 1.0].
    """
    if not 0.0 <= ai_share <= 1.0:
        raise ValueError(
            f"ai_share must be between 0.0 and 1.0, got {ai_share}"
        )

    effective_total = _resolve_total_platform_ai_downloads(
        platform, total_platform_ai_downloads
    )

    package_ai_downloads_annual = _annualised_ai_downloads(package_stats, ai_share)
    package_share = _compute_package_download_share(
        package_ai_downloads_annual, effective_total
    )

    annual_oss_pool = platform.annual_oss_pool
    annual_revenue = annual_oss_pool * package_share
    monthly_revenue = annual_revenue / 12.0

    notes = (
        f"Pro-rata model: package AI downloads (annual) = {package_ai_downloads_annual:,}; "
        f"total platform AI downloads = {effective_total:,}; "
        f"package share = {package_share * 100:.6f}%; "
        f"annual OSS pool = ${annual_oss_pool:,.2f}."
    )

    logger.debug(
        "calculate_prorata: %s@%s ai_annual=%d total=%d share=%.8f "
        "oss_pool=$%.2f annual=$%.4f",
        package_stats.package_name,
        platform.slug,
        package_ai_downloads_annual,
        effective_total,
        package_share,
        annual_oss_pool,
        annual_revenue,
    )

    return ModelResult(
        model=RevenueModel.PRORATA,
        annual_revenue_usd=annual_revenue,
        monthly_revenue_usd=monthly_revenue,
        notes=notes,
    )


def calculate_peruse(
    package_stats: PackageStats,
    platform: PlatformConfig,
    ai_share: float,
) -> ModelResult:
    """Compute a per-use micro-payment revenue estimate.

    The platform pays a derived micro-payment rate for each AI-attributed
    download event.  The rate is calculated as the fraction of ARPU that the
    platform designates for OSS divided by the assumed number of download
    events per subscriber per month.

    Formula::

        per_download_rate = (monthly_arpu × oss_revenue_share)
                            / downloads_per_subscriber_per_month
        annual_ai_downloads = total_downloads × ai_share × (365 / period_days)
        annual_revenue = annual_ai_downloads × per_download_rate

    Note that ``per_download_rate`` is already a per-download annual rate when
    multiplied by annual AI downloads — there is no additional ×12 factor
    because ``annual_ai_downloads`` is already annualised.

    The underlying logic is::

        monthly_oss_per_subscriber = monthly_arpu × oss_revenue_share
        total_monthly_platform_ai_downloads = subscribers × dps_per_month
        per_download_rate = monthly_oss_per_subscriber / dps_per_month
                          = (monthly_arpu × oss_revenue_share) / dps_per_month
        monthly_revenue = annual_ai_downloads / 12 × per_download_rate
        annual_revenue  = annual_ai_downloads × per_download_rate

    Args:
        package_stats: Download statistics for the package.
        platform: Platform configuration.
        ai_share: Fraction of downloads attributed to AI (0.0–1.0).

    Returns:
        A :class:`~oss_revenue_calc.models.ModelResult` for the per-use model.

    Raises:
        ValueError: If ``ai_share`` is outside [0.0, 1.0].
    """
    if not 0.0 <= ai_share <= 1.0:
        raise ValueError(
            f"ai_share must be between 0.0 and 1.0, got {ai_share}"
        )

    # Derive per-download micro-payment rate
    per_download_rate = _compute_per_download_rate(platform)

    # Annualise the package's AI-attributed downloads
    annual_ai_downloads = _annualised_ai_downloads(package_stats, ai_share)

    annual_revenue = annual_ai_downloads * per_download_rate
    monthly_revenue = annual_revenue / 12.0

    notes = (
        f"Per-use model: per-download rate = ${per_download_rate:.8f}; "
        f"annual AI downloads = {annual_ai_downloads:,}; "
        f"rate = ARPU (${platform.monthly_arpu:.2f}) × OSS share "
        f"({platform.oss_revenue_share * 100:.1f}%) / "
        f"downloads per subscriber per month "
        f"({platform.downloads_per_subscriber_per_month:,.0f})."
    )

    logger.debug(
        "calculate_peruse: %s@%s per_download_rate=%.8f "
        "annual_ai=%d annual=$%.4f",
        package_stats.package_name,
        platform.slug,
        per_download_rate,
        annual_ai_downloads,
        annual_revenue,
    )

    return ModelResult(
        model=RevenueModel.PERUSE,
        annual_revenue_usd=annual_revenue,
        monthly_revenue_usd=monthly_revenue,
        notes=notes,
    )


def calculate_revenue_for_platforms(
    package_stats: PackageStats,
    platforms: list[PlatformConfig],
    ai_share: float,
    model: RevenueModel = RevenueModel.BOTH,
) -> list[RevenueResult]:
    """Calculate revenue estimates for a package across multiple platforms.

    Convenience wrapper around :func:`calculate_revenue` that iterates over a
    list of platforms and returns one :class:`~oss_revenue_calc.models.RevenueResult`
    per platform.

    Args:
        package_stats: Download statistics for the target package.
        platforms: List of platform configurations to evaluate.
        ai_share: Fraction of downloads attributed to AI (0.0–1.0).
        model: Which revenue model(s) to compute.

    Returns:
        A list of :class:`~oss_revenue_calc.models.RevenueResult` objects, one
        per platform, in the same order as the input ``platforms`` list.

    Raises:
        ValueError: If ``ai_share`` is outside [0.0, 1.0].

    Example::

        from oss_revenue_calc.platforms import list_platforms

        results = calculate_revenue_for_platforms(
            stats, list_platforms(), ai_share=0.30
        )
        for r in results:
            print(r.platform.name, r.average_annual_revenue)
    """
    if not 0.0 <= ai_share <= 1.0:
        raise ValueError(
            f"ai_share must be between 0.0 and 1.0, got {ai_share}"
        )

    results: list[RevenueResult] = []
    for platform in platforms:
        result = calculate_revenue(
            package_stats=package_stats,
            platform=platform,
            ai_share=ai_share,
            model=model,
        )
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _annualised_ai_downloads(
    package_stats: PackageStats,
    ai_share: float,
) -> int:
    """Return the estimated annual AI-attributed download count.

    Scales the package's download total to a 365-day basis and applies the
    ``ai_share`` fraction.

    Args:
        package_stats: Download statistics including raw total and period.
        ai_share: Fraction of downloads attributed to AI (0.0–1.0).

    Returns:
        Integer annual AI-attributed download count (always >= 0).
    """
    annual_total = package_stats.annualised_downloads()
    return int(annual_total * ai_share)


def _compute_per_download_rate(platform: PlatformConfig) -> float:
    """Derive the per-download micro-payment rate for the per-use model.

    The rate is the portion of monthly ARPU allocated to OSS divided by the
    assumed number of download events attributed to each subscriber per month::

        rate = (monthly_arpu × oss_revenue_share)
               / downloads_per_subscriber_per_month

    Args:
        platform: Platform configuration.

    Returns:
        Per-download rate in USD (a small positive float, typically fractions
        of a cent).

    Raises:
        ValueError: If ``downloads_per_subscriber_per_month`` is zero or
            negative (should be caught by :class:`PlatformConfig` validation,
            but guarded here for safety).
    """
    if platform.downloads_per_subscriber_per_month <= 0:
        raise ValueError(
            "downloads_per_subscriber_per_month must be positive for per-use "
            f"model calculation, got {platform.downloads_per_subscriber_per_month}"
        )
    monthly_oss_per_subscriber = (
        platform.monthly_arpu * platform.oss_revenue_share
    )
    return monthly_oss_per_subscriber / platform.downloads_per_subscriber_per_month


def _estimate_total_platform_ai_downloads(platform: PlatformConfig) -> int:
    """Estimate total annual AI-attributed downloads across all packages on a platform.

    Uses the platform's subscriber count and
    ``downloads_per_subscriber_per_month`` to derive a total::

        total = subscribers × downloads_per_subscriber_per_month × 12

    This figure represents the denominator in the pro-rata share calculation.
    It is intentionally an overestimate (not all platform-attributed downloads
    involve OSS packages), which makes the resulting revenue estimate
    conservative.

    Args:
        platform: Platform configuration.

    Returns:
        Estimated total annual AI-attributed downloads as an integer.
    """
    total = (
        platform.subscribers
        * platform.downloads_per_subscriber_per_month
        * 12
    )
    return max(1, int(total))  # avoid division by zero


def _resolve_total_platform_ai_downloads(
    platform: PlatformConfig,
    total_platform_ai_downloads: Optional[int],
) -> int:
    """Resolve the effective total platform AI downloads, estimating if needed.

    Args:
        platform: Platform configuration (used for estimation if needed).
        total_platform_ai_downloads: Caller-supplied value, or ``None``.

    Returns:
        A positive integer total platform AI download count.
    """
    if total_platform_ai_downloads is not None:
        return max(1, total_platform_ai_downloads)
    return _estimate_total_platform_ai_downloads(platform)


def _compute_package_download_share(
    package_ai_downloads_annual: int,
    total_platform_ai_downloads: int,
) -> float:
    """Compute the package's fractional share of total platform AI downloads.

    Args:
        package_ai_downloads_annual: The package's annualised AI-attributed
            download count.
        total_platform_ai_downloads: Total annual AI-attributed download count
            across all packages on the platform (must be > 0).

    Returns:
        A float in [0.0, 1.0] representing the package's download share.
        Capped at 1.0 in case the package exceeds the estimated total.
    """
    if total_platform_ai_downloads <= 0:
        return 0.0
    share = package_ai_downloads_annual / total_platform_ai_downloads
    # Cap at 1.0 to handle edge cases where per-package estimate exceeds total
    return min(1.0, share)
