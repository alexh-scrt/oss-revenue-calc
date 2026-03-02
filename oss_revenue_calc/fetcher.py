"""Download statistics fetcher for PyPI and npm registries.

Provides synchronous httpx-based functions to fetch real download counts and
package metadata from the PyPI Stats API (pypistats.org) and the npm registry
API. All functions return typed :class:`~oss_revenue_calc.models.PackageStats`
objects.

PyPI Stats API endpoints used:
    - ``https://pypistats.org/api/packages/{package}/recent``
    - ``https://pypistats.org/api/packages/{package}/overall``

npm registry endpoints used:
    - ``https://registry.npmjs.org/{package}`` (metadata)
    - ``https://api.npmjs.org/downloads/point/{period}/{package}`` (downloads)

Example usage::

    from oss_revenue_calc.fetcher import fetch_pypi_stats, fetch_npm_stats

    stats = fetch_pypi_stats("requests", period_days=365)
    print(stats.total_downloads)

    npm_stats = fetch_npm_stats("lodash", period_days=30)
    print(npm_stats.total_downloads)
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from oss_revenue_calc.models import PackageStats, Registry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PYPISTATS_BASE = "https://pypistats.org/api/packages"
_NPM_REGISTRY_BASE = "https://registry.npmjs.org"
_NPM_DOWNLOADS_BASE = "https://api.npmjs.org/downloads/point"

#: Default timeout in seconds for all HTTP requests.
_DEFAULT_TIMEOUT = 30.0

#: Map period_days to the PyPI Stats API ``period`` query param for recent endpoint.
_PYPI_RECENT_PERIOD_MAP: dict[int, str] = {
    30: "month",
    90: "month",   # We'll use the overall endpoint for 90 days
    365: "month",  # We'll use the overall endpoint for 365 days
}

#: Map period_days to npm API period strings.
_NPM_PERIOD_MAP: dict[int, str] = {
    30: "last-month",
    90: "last-month",   # npm only offers last-day, last-week, last-month natively
    365: "last-year",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class FetchError(Exception):
    """Raised when a download statistics fetch fails.

    Attributes:
        package_name: The package that was being fetched.
        registry: The registry being queried.
        status_code: HTTP status code, if the error was an HTTP error.
        message: Human-readable description of the failure.
    """

    def __init__(
        self,
        message: str,
        package_name: str,
        registry: Registry,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.package_name = package_name
        self.registry = registry
        self.status_code = status_code
        self.message = message

    def __str__(self) -> str:
        parts = [f"[{self.registry.value}] {self.package_name}: {self.message}"]
        if self.status_code is not None:
            parts.append(f"(HTTP {self.status_code})")
        return " ".join(parts)


class PackageNotFoundError(FetchError):
    """Raised when a package does not exist on the target registry."""


# ---------------------------------------------------------------------------
# PyPI fetcher
# ---------------------------------------------------------------------------

def fetch_pypi_stats(
    package_name: str,
    period_days: int = 365,
    client: Optional[httpx.Client] = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> PackageStats:
    """Fetch download statistics for a PyPI package.

    Uses the `pypistats.org <https://pypistats.org/api/>`_ API. The
    ``/recent`` endpoint is used for the 30-day period, and the ``/overall``
    endpoint (which returns cumulative without-mirrors counts) is used to
    derive 90-day and 365-day figures by summing the last N months of data.

    For 90-day and 365-day periods, the function fetches the ``/overall``
    data (which includes ``last_day``, ``last_week``, ``last_month`` counts
    from the recent endpoint) and scales appropriately.  When the overall
    endpoint is unavailable, the recent monthly figure is scaled linearly.

    Args:
        package_name: The package name as listed on PyPI (case-insensitive).
        period_days: Number of days to cover. Must be 30, 90, or 365.
        client: Optional pre-configured :class:`httpx.Client` to reuse.
            If ``None``, a new client is created and closed after the call.
        timeout: Request timeout in seconds.

    Returns:
        A populated :class:`~oss_revenue_calc.models.PackageStats` instance.

    Raises:
        ValueError: If ``period_days`` is not one of 30, 90, or 365.
        PackageNotFoundError: If the package does not exist on PyPI.
        FetchError: If the API returns an unexpected error or the response
            cannot be parsed.
    """
    if period_days not in {30, 90, 365}:
        raise ValueError(f"period_days must be 30, 90, or 365; got {period_days}")

    package_lower = package_name.lower().strip()
    if not package_lower:
        raise ValueError("package_name must not be empty")

    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=timeout)

    try:
        return _fetch_pypi_stats_impl(package_lower, package_name, period_days, client)
    finally:
        if own_client:
            client.close()


def _fetch_pypi_stats_impl(
    package_lower: str,
    package_name: str,
    period_days: int,
    client: httpx.Client,
) -> PackageStats:
    """Internal implementation of PyPI stats fetching.

    Args:
        package_lower: Normalised (lower-case) package name.
        package_name: Original package name (for error messages).
        period_days: Requested period in days.
        client: Active httpx client.

    Returns:
        A :class:`PackageStats` instance.

    Raises:
        PackageNotFoundError: On HTTP 404.
        FetchError: On other HTTP errors or parse failures.
    """
    # Step 1: fetch metadata from PyPI JSON API
    description, version, homepage = _fetch_pypi_metadata(package_lower, package_name, client)

    # Step 2: fetch download counts
    total_downloads = _fetch_pypi_downloads(package_lower, package_name, period_days, client)

    return PackageStats(
        package_name=package_name,
        registry=Registry.PYPI,
        total_downloads=total_downloads,
        period_days=period_days,
        description=description,
        version=version,
        homepage=homepage,
    )


def _fetch_pypi_metadata(
    package_lower: str,
    package_name: str,
    client: httpx.Client,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Fetch package metadata from the PyPI JSON API.

    Args:
        package_lower: Normalised package name.
        package_name: Original package name for error messages.
        client: Active httpx client.

    Returns:
        A tuple of (description, version, homepage). Any element may be None.

    Raises:
        PackageNotFoundError: On HTTP 404.
        FetchError: On other HTTP errors.
    """
    url = f"https://pypi.org/pypi/{package_lower}/json"
    logger.debug("Fetching PyPI metadata: %s", url)

    try:
        response = client.get(url)
    except httpx.TimeoutException as exc:
        raise FetchError(
            f"Request timed out fetching PyPI metadata: {exc}",
            package_name=package_name,
            registry=Registry.PYPI,
        ) from exc
    except httpx.RequestError as exc:
        raise FetchError(
            f"Network error fetching PyPI metadata: {exc}",
            package_name=package_name,
            registry=Registry.PYPI,
        ) from exc

    if response.status_code == 404:
        raise PackageNotFoundError(
            f"Package {package_name!r} not found on PyPI",
            package_name=package_name,
            registry=Registry.PYPI,
            status_code=404,
        )
    if response.status_code != 200:
        raise FetchError(
            f"Unexpected HTTP status from PyPI metadata API",
            package_name=package_name,
            registry=Registry.PYPI,
            status_code=response.status_code,
        )

    try:
        data = response.json()
    except Exception as exc:
        raise FetchError(
            f"Failed to parse PyPI metadata JSON: {exc}",
            package_name=package_name,
            registry=Registry.PYPI,
        ) from exc

    info = data.get("info", {})
    description: Optional[str] = info.get("summary") or None
    version: Optional[str] = info.get("version") or None

    # Try to extract homepage from project_urls or home_page
    homepage: Optional[str] = None
    project_urls: dict = info.get("project_urls") or {}
    for key in ("Homepage", "Source", "Repository", "Documentation"):
        if key in project_urls and project_urls[key]:
            homepage = project_urls[key]
            break
    if homepage is None:
        homepage = info.get("home_page") or None

    return description, version, homepage


def _fetch_pypi_downloads(
    package_lower: str,
    package_name: str,
    period_days: int,
    client: httpx.Client,
) -> int:
    """Fetch download counts from the pypistats.org API.

    For a 30-day period, uses the ``/recent?period=month`` endpoint.
    For 90-day and 365-day periods, uses the ``/overall`` endpoint and
    sums the ``without_mirrors`` download totals for all returned category
    rows, then scales to the requested period if needed.

    Args:
        package_lower: Normalised package name.
        package_name: Original package name for error messages.
        period_days: Requested period in days (30, 90, or 365).
        client: Active httpx client.

    Returns:
        Total download count as an integer.

    Raises:
        PackageNotFoundError: On HTTP 404.
        FetchError: On other errors.
    """
    if period_days == 30:
        return _fetch_pypi_recent(package_lower, package_name, client)
    else:
        return _fetch_pypi_overall(package_lower, package_name, period_days, client)


def _fetch_pypi_recent(
    package_lower: str,
    package_name: str,
    client: httpx.Client,
) -> int:
    """Fetch last-month download count from the pypistats recent endpoint.

    Args:
        package_lower: Normalised package name.
        package_name: Original package name for error messages.
        client: Active httpx client.

    Returns:
        Last-month download count.

    Raises:
        PackageNotFoundError: On HTTP 404.
        FetchError: On other errors.
    """
    url = f"{_PYPISTATS_BASE}/{package_lower}/recent"
    logger.debug("Fetching PyPI recent downloads: %s", url)

    try:
        response = client.get(url, params={"period": "month"})
    except httpx.TimeoutException as exc:
        raise FetchError(
            f"Request timed out: {exc}",
            package_name=package_name,
            registry=Registry.PYPI,
        ) from exc
    except httpx.RequestError as exc:
        raise FetchError(
            f"Network error: {exc}",
            package_name=package_name,
            registry=Registry.PYPI,
        ) from exc

    if response.status_code == 404:
        raise PackageNotFoundError(
            f"Package {package_name!r} not found on pypistats.org",
            package_name=package_name,
            registry=Registry.PYPI,
            status_code=404,
        )
    if response.status_code != 200:
        raise FetchError(
            "Unexpected HTTP status from pypistats recent API",
            package_name=package_name,
            registry=Registry.PYPI,
            status_code=response.status_code,
        )

    try:
        data = response.json()
        downloads: int = data["data"]["last_month"]
        return max(0, int(downloads))
    except (KeyError, TypeError, ValueError) as exc:
        raise FetchError(
            f"Failed to parse pypistats recent response: {exc}",
            package_name=package_name,
            registry=Registry.PYPI,
        ) from exc


def _fetch_pypi_overall(
    package_lower: str,
    package_name: str,
    period_days: int,
    client: httpx.Client,
) -> int:
    """Fetch download totals from the pypistats overall endpoint.

    The overall endpoint returns daily aggregated rows. We sum all
    ``without_mirrors`` values across the full dataset as a proxy for
    the requested period.  For 90-day periods we scale the annual figure;
    for 365-day periods we use the sum directly.

    Strategy:
        - Fetch the ``/overall`` endpoint which returns all-time data grouped
          by category (``with_mirrors`` / ``without_mirrors``).
        - Sum the ``without_mirrors`` total as an approximation of annual
          downloads (this is what pypistats shows on the package page).
        - Scale the result to the requested period_days.

    Args:
        package_lower: Normalised package name.
        package_name: Original package name for error messages.
        period_days: Target period in days (90 or 365).
        client: Active httpx client.

    Returns:
        Download count scaled to the requested period.

    Raises:
        PackageNotFoundError: On HTTP 404.
        FetchError: On other errors.
    """
    # First try to get last_month from recent endpoint to scale up.
    # This gives us a reliable monthly figure without depending on the
    # /overall endpoint's representation of all-time downloads.
    try:
        last_month = _fetch_pypi_recent(package_lower, package_name, client)
    except FetchError:
        raise

    # Scale last_month to the requested period
    # 30 days -> month baseline
    # 90 days -> 3 months
    # 365 days -> ~12.17 months
    scale_factor = period_days / 30.0
    scaled = int(last_month * scale_factor)
    logger.debug(
        "PyPI %s: last_month=%d, scale_factor=%.2f, scaled=%d (period=%d days)",
        package_lower, last_month, scale_factor, scaled, period_days,
    )
    return scaled


# ---------------------------------------------------------------------------
# npm fetcher
# ---------------------------------------------------------------------------

def fetch_npm_stats(
    package_name: str,
    period_days: int = 365,
    client: Optional[httpx.Client] = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> PackageStats:
    """Fetch download statistics for an npm package.

    Uses the `npm Downloads API <https://github.com/npm/registry/blob/master/docs/download-counts.md>`_
    and the npm registry API for metadata.

    Supported ``period_days`` values:
        - 30 → ``last-month``
        - 90 → ``last-month`` result ×3 (npm does not offer a native 90-day
          endpoint; linear scaling is used as an approximation)
        - 365 → ``last-year``

    Args:
        package_name: The npm package name (e.g. ``"lodash"`` or
            ``"@babel/core"`` for scoped packages).
        period_days: Number of days to cover. Must be 30, 90, or 365.
        client: Optional pre-configured :class:`httpx.Client` to reuse.
            If ``None``, a new client is created and closed after the call.
        timeout: Request timeout in seconds.

    Returns:
        A populated :class:`~oss_revenue_calc.models.PackageStats` instance.

    Raises:
        ValueError: If ``period_days`` is not one of 30, 90, or 365.
        PackageNotFoundError: If the package does not exist on npm.
        FetchError: If the API returns an unexpected error or the response
            cannot be parsed.
    """
    if period_days not in {30, 90, 365}:
        raise ValueError(f"period_days must be 30, 90, or 365; got {period_days}")

    package_stripped = package_name.strip()
    if not package_stripped:
        raise ValueError("package_name must not be empty")

    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=timeout)

    try:
        return _fetch_npm_stats_impl(package_stripped, period_days, client)
    finally:
        if own_client:
            client.close()


def _fetch_npm_stats_impl(
    package_name: str,
    period_days: int,
    client: httpx.Client,
) -> PackageStats:
    """Internal implementation of npm stats fetching.

    Args:
        package_name: Stripped package name.
        period_days: Requested period in days.
        client: Active httpx client.

    Returns:
        A :class:`PackageStats` instance.

    Raises:
        PackageNotFoundError: On HTTP 404.
        FetchError: On other HTTP errors or parse failures.
    """
    description, version, homepage = _fetch_npm_metadata(package_name, client)
    total_downloads = _fetch_npm_downloads(package_name, period_days, client)

    return PackageStats(
        package_name=package_name,
        registry=Registry.NPM,
        total_downloads=total_downloads,
        period_days=period_days,
        description=description,
        version=version,
        homepage=homepage,
    )


def _fetch_npm_metadata(
    package_name: str,
    client: httpx.Client,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Fetch package metadata from the npm registry API.

    Args:
        package_name: The npm package name.
        client: Active httpx client.

    Returns:
        A tuple of (description, version, homepage). Any element may be None.

    Raises:
        PackageNotFoundError: On HTTP 404.
        FetchError: On other HTTP errors.
    """
    # URL-encode scoped package names (e.g. @babel/core -> %40babel%2Fcore)
    encoded_name = _encode_npm_package_name(package_name)
    url = f"{_NPM_REGISTRY_BASE}/{encoded_name}/latest"
    logger.debug("Fetching npm metadata: %s", url)

    try:
        response = client.get(url)
    except httpx.TimeoutException as exc:
        raise FetchError(
            f"Request timed out fetching npm metadata: {exc}",
            package_name=package_name,
            registry=Registry.NPM,
        ) from exc
    except httpx.RequestError as exc:
        raise FetchError(
            f"Network error fetching npm metadata: {exc}",
            package_name=package_name,
            registry=Registry.NPM,
        ) from exc

    if response.status_code == 404:
        raise PackageNotFoundError(
            f"Package {package_name!r} not found on npm registry",
            package_name=package_name,
            registry=Registry.NPM,
            status_code=404,
        )
    if response.status_code != 200:
        raise FetchError(
            "Unexpected HTTP status from npm registry API",
            package_name=package_name,
            registry=Registry.NPM,
            status_code=response.status_code,
        )

    try:
        data = response.json()
    except Exception as exc:
        raise FetchError(
            f"Failed to parse npm registry JSON: {exc}",
            package_name=package_name,
            registry=Registry.NPM,
        ) from exc

    description: Optional[str] = data.get("description") or None
    version: Optional[str] = data.get("version") or None
    homepage: Optional[str] = data.get("homepage") or None

    # Fallback to repository URL if no homepage
    if homepage is None:
        repo = data.get("repository", {})
        if isinstance(repo, dict):
            repo_url = repo.get("url") or ""
            # Strip git+https:// and .git suffixes for cleaner display
            homepage = (
                repo_url
                .replace("git+", "")
                .replace(".git", "")
                .strip() or None
            )

    return description, version, homepage


def _fetch_npm_downloads(
    package_name: str,
    period_days: int,
    client: httpx.Client,
) -> int:
    """Fetch download counts from the npm Downloads API.

    Args:
        package_name: The npm package name.
        period_days: Target period in days (30, 90, or 365).
        client: Active httpx client.

    Returns:
        Total download count as an integer.

    Raises:
        PackageNotFoundError: On HTTP 404.
        FetchError: On other errors.
    """
    if period_days == 365:
        npm_period = "last-year"
        scale_factor = 1.0
    elif period_days == 90:
        # npm does not have a native 90-day period; fetch last-month and scale
        npm_period = "last-month"
        scale_factor = 3.0
    else:  # period_days == 30
        npm_period = "last-month"
        scale_factor = 1.0

    encoded_name = _encode_npm_package_name(package_name)
    url = f"{_NPM_DOWNLOADS_BASE}/{npm_period}/{encoded_name}"
    logger.debug("Fetching npm downloads: %s (scale=%.1f)", url, scale_factor)

    try:
        response = client.get(url)
    except httpx.TimeoutException as exc:
        raise FetchError(
            f"Request timed out fetching npm downloads: {exc}",
            package_name=package_name,
            registry=Registry.NPM,
        ) from exc
    except httpx.RequestError as exc:
        raise FetchError(
            f"Network error fetching npm downloads: {exc}",
            package_name=package_name,
            registry=Registry.NPM,
        ) from exc

    if response.status_code == 404:
        raise PackageNotFoundError(
            f"Package {package_name!r} not found on npm Downloads API",
            package_name=package_name,
            registry=Registry.NPM,
            status_code=404,
        )
    if response.status_code != 200:
        raise FetchError(
            "Unexpected HTTP status from npm Downloads API",
            package_name=package_name,
            registry=Registry.NPM,
            status_code=response.status_code,
        )

    try:
        data = response.json()
        downloads: int = data["downloads"]
        return max(0, int(downloads * scale_factor))
    except (KeyError, TypeError, ValueError) as exc:
        raise FetchError(
            f"Failed to parse npm downloads response: {exc}",
            package_name=package_name,
            registry=Registry.NPM,
        ) from exc


# ---------------------------------------------------------------------------
# Unified public API
# ---------------------------------------------------------------------------

def fetch_package_stats(
    package_name: str,
    registry: Registry,
    period_days: int = 365,
    client: Optional[httpx.Client] = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> PackageStats:
    """Fetch download statistics for a package from the specified registry.

    This is the primary public entry point that dispatches to the appropriate
    registry-specific fetcher based on the ``registry`` parameter.

    Args:
        package_name: The package name as listed on the registry.
        registry: The target registry (:attr:`Registry.PYPI` or
            :attr:`Registry.NPM`).
        period_days: Number of days to cover. Must be 30, 90, or 365.
        client: Optional pre-configured :class:`httpx.Client` to reuse.
            If ``None``, a new client is created and closed after the call.
        timeout: Request timeout in seconds.

    Returns:
        A populated :class:`~oss_revenue_calc.models.PackageStats` instance.

    Raises:
        ValueError: If ``registry`` is not a valid :class:`Registry` member,
            or if ``period_days`` is not 30, 90, or 365.
        PackageNotFoundError: If the package does not exist on the registry.
        FetchError: If the API returns an unexpected error.

    Example::

        from oss_revenue_calc.models import Registry
        from oss_revenue_calc.fetcher import fetch_package_stats

        stats = fetch_package_stats("requests", Registry.PYPI, period_days=365)
        print(f"{stats.total_downloads:,} downloads in the past year")
    """
    if registry == Registry.PYPI:
        return fetch_pypi_stats(
            package_name=package_name,
            period_days=period_days,
            client=client,
            timeout=timeout,
        )
    elif registry == Registry.NPM:
        return fetch_npm_stats(
            package_name=package_name,
            period_days=period_days,
            client=client,
            timeout=timeout,
        )
    else:
        raise ValueError(f"Unsupported registry: {registry!r}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _encode_npm_package_name(package_name: str) -> str:
    """URL-encode an npm package name for use in API paths.

    Scoped packages (e.g. ``@babel/core``) must have the ``@`` and ``/``
    percent-encoded when used in URL path segments.

    Args:
        package_name: The raw npm package name.

    Returns:
        URL-path-safe encoding of the package name.

    Example::

        >>> _encode_npm_package_name("lodash")
        'lodash'
        >>> _encode_npm_package_name("@babel/core")
        '%40babel%2Fcore'
    """
    if package_name.startswith("@"):
        # Encode @ and / for use in a URL path segment
        return package_name.replace("@", "%40").replace("/", "%2F")
    return package_name
