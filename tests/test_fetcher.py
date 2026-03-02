"""Tests for oss_revenue_calc.fetcher using mocked HTTP responses.

Covers both the PyPI Stats / PyPI JSON API fetchers and the npm registry /
npm Downloads API fetchers. All network calls are intercepted with
pytest-httpx so no real HTTP requests are made during testing.
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from oss_revenue_calc.fetcher import (
    FetchError,
    PackageNotFoundError,
    _encode_npm_package_name,
    fetch_npm_stats,
    fetch_package_stats,
    fetch_pypi_stats,
)
from oss_revenue_calc.models import Registry


# ---------------------------------------------------------------------------
# Constants / URL helpers
# ---------------------------------------------------------------------------

PYPI_METADATA_URL = "https://pypi.org/pypi/requests/json"
PYPISTATS_RECENT_URL = "https://pypistats.org/api/packages/requests/recent"
PYPISTATS_RECENT_URL_WITH_PERIOD = (
    "https://pypistats.org/api/packages/requests/recent?period=month"
)

NPM_METADATA_URL = "https://registry.npmjs.org/lodash/latest"
NPM_DOWNLOADS_YEAR_URL = "https://api.npmjs.org/downloads/point/last-year/lodash"
NPM_DOWNLOADS_MONTH_URL = "https://api.npmjs.org/downloads/point/last-month/lodash"


# ---------------------------------------------------------------------------
# Response body factories
# ---------------------------------------------------------------------------

def _pypi_metadata_body(
    summary: str = "HTTP for Humans",
    version: str = "2.31.0",
    homepage: str = "https://requests.readthedocs.io",
    project_urls: dict | None = None,
) -> dict:
    """Build a minimal PyPI JSON API response body."""
    if project_urls is None:
        project_urls = {"Homepage": homepage}
    return {
        "info": {
            "summary": summary,
            "version": version,
            "home_page": homepage,
            "project_urls": project_urls,
        }
    }


def _pypi_recent_body(last_month: int = 5_000_000) -> dict:
    """Build a minimal pypistats recent API response body."""
    return {
        "data": {
            "last_day": 200_000,
            "last_week": 1_200_000,
            "last_month": last_month,
        },
        "package": "requests",
        "type": "recent_downloads",
    }


def _npm_metadata_body(
    description: str = "Lodash modular utilities",
    version: str = "4.17.21",
    homepage: str = "https://lodash.com",
) -> dict:
    """Build a minimal npm registry API response body."""
    return {
        "name": "lodash",
        "description": description,
        "version": version,
        "homepage": homepage,
    }


def _npm_downloads_body(
    downloads: int = 100_000_000,
    package: str = "lodash",
) -> dict:
    """Build a minimal npm Downloads API response body."""
    return {
        "downloads": downloads,
        "package": package,
        "start": "2023-01-01",
        "end": "2023-12-31",
    }


# ---------------------------------------------------------------------------
# PyPI fetcher — happy path tests
# ---------------------------------------------------------------------------

class TestFetchPypiStatsHappyPath:
    """Happy-path integration tests for fetch_pypi_stats."""

    def test_30_day_period_returns_last_month(self, httpx_mock: HTTPXMock) -> None:
        """30-day period: uses recent endpoint, returns last_month count."""
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(version="2.31.0"),
        )
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(version="2.31.0"),
        )
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(version="2.31.0"),
        )
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(version="2.31.0"),
        )
        # Use the correct URL matching approach:
        # The fetcher calls: metadata URL then recent URL with ?period=month
        pass  # Covered by the integrated class below


class TestFetchPypiStats:
    """Integration-style tests with correct URL matching for fetch_pypi_stats."""

    def test_30_day_period(self, httpx_mock: HTTPXMock) -> None:
        """30-day period: uses recent endpoint, returns last_month count."""
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(version="2.31.0"),
        )
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(version="2.31.0"),
        )
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(version="2.31.0"),
        )
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(version="2.31.0"),
        )
        pass  # Covered below

    def test_30d_correct_total(self, httpx_mock: HTTPXMock) -> None:
        """30-day: returns exactly last_month download count."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(version="2.31.0"),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(last_month=4_500_000),
        )

        stats = fetch_pypi_stats("requests", period_days=30)

        assert stats.package_name == "requests"
        assert stats.registry == Registry.PYPI
        assert stats.total_downloads == 4_500_000
        assert stats.period_days == 30
        assert stats.version == "2.31.0"
        assert stats.description == "HTTP for Humans"

    def test_365_day_period_scales_monthly(self, httpx_mock: HTTPXMock) -> None:
        """365-day period: fetches monthly count, then scales by 365/30."""
        last_month = 3_000_000
        expected = int(last_month * (365 / 30))

        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(last_month=last_month),
        )

        stats = fetch_pypi_stats("requests", period_days=365)

        assert stats.total_downloads == expected
        assert stats.period_days == 365

    def test_90_day_period_scales_monthly(self, httpx_mock: HTTPXMock) -> None:
        """90-day period: fetches monthly count, then scales by 90/30 = 3."""
        last_month = 2_000_000
        expected = int(last_month * (90 / 30))

        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(last_month=last_month),
        )

        stats = fetch_pypi_stats("requests", period_days=90)

        assert stats.total_downloads == expected
        assert stats.period_days == 90

    def test_metadata_fields_populated(self, httpx_mock: HTTPXMock) -> None:
        """Metadata fields (description, version, homepage) are correctly parsed."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json={
                "info": {
                    "summary": "HTTP for Humans.",
                    "version": "2.31.0",
                    "home_page": "https://requests.readthedocs.io",
                    "project_urls": {
                        "Homepage": "https://requests.readthedocs.io",
                    },
                }
            },
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(),
        )

        stats = fetch_pypi_stats("requests", period_days=30)

        assert stats.description == "HTTP for Humans."
        assert stats.version == "2.31.0"
        assert stats.homepage == "https://requests.readthedocs.io"

    def test_homepage_fallback_to_home_page(self, httpx_mock: HTTPXMock) -> None:
        """Falls back to home_page when project_urls has no Homepage entry."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json={
                "info": {
                    "summary": "A package",
                    "version": "1.0.0",
                    "home_page": "https://example.com",
                    "project_urls": {},
                }
            },
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(),
        )

        stats = fetch_pypi_stats("requests", period_days=30)
        assert stats.homepage == "https://example.com"

    def test_project_urls_homepage_preferred_over_home_page(self, httpx_mock: HTTPXMock) -> None:
        """project_urls['Homepage'] takes priority over home_page."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json={
                "info": {
                    "summary": "A package",
                    "version": "1.0.0",
                    "home_page": "https://old-homepage.com",
                    "project_urls": {
                        "Homepage": "https://new-homepage.com",
                    },
                }
            },
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(),
        )

        stats = fetch_pypi_stats("requests", period_days=30)
        assert stats.homepage == "https://new-homepage.com"

    def test_project_urls_source_fallback(self, httpx_mock: HTTPXMock) -> None:
        """Falls back to project_urls['Source'] when Homepage is absent."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json={
                "info": {
                    "summary": "A package",
                    "version": "1.0.0",
                    "home_page": None,
                    "project_urls": {
                        "Source": "https://github.com/example/pkg",
                    },
                }
            },
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(),
        )

        stats = fetch_pypi_stats("requests", period_days=30)
        assert stats.homepage == "https://github.com/example/pkg"

    def test_missing_optional_metadata_is_none(self, httpx_mock: HTTPXMock) -> None:
        """Missing optional metadata fields resolve to None."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json={
                "info": {
                    "summary": None,
                    "version": None,
                    "home_page": None,
                    "project_urls": None,
                }
            },
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(),
        )

        stats = fetch_pypi_stats("requests", period_days=30)
        assert stats.description is None
        assert stats.version is None
        assert stats.homepage is None

    def test_zero_downloads_returns_zero(self, httpx_mock: HTTPXMock) -> None:
        """Zero downloads from API returns a valid stats object with 0."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(last_month=0),
        )

        stats = fetch_pypi_stats("requests", period_days=30)
        assert stats.total_downloads == 0

    def test_package_name_lowercased_in_url(self, httpx_mock: HTTPXMock) -> None:
        """Package names are normalised to lowercase for URL construction."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(),
        )

        # 'Requests' normalises to 'requests' for URL construction
        stats = fetch_pypi_stats("Requests", period_days=30)
        # Original name is preserved in the result
        assert stats.package_name == "Requests"
        assert stats.registry == Registry.PYPI

    def test_large_download_count(self, httpx_mock: HTTPXMock) -> None:
        """Large download counts are handled correctly."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(last_month=500_000_000),
        )

        stats = fetch_pypi_stats("requests", period_days=30)
        assert stats.total_downloads == 500_000_000


# ---------------------------------------------------------------------------
# PyPI fetcher — error handling tests
# ---------------------------------------------------------------------------

class TestFetchPypiStatsErrors:
    """Error handling tests for fetch_pypi_stats."""

    def test_pypi_metadata_404_raises_package_not_found(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 404 from PyPI metadata API raises PackageNotFoundError."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/nonexistent-xyz-123/json",
            status_code=404,
            json={"message": "Not Found"},
        )

        with pytest.raises(PackageNotFoundError) as exc_info:
            fetch_pypi_stats("nonexistent-xyz-123", period_days=30)

        assert exc_info.value.registry == Registry.PYPI
        assert exc_info.value.status_code == 404
        assert "nonexistent-xyz-123" in str(exc_info.value)

    def test_pypistats_recent_404_raises_package_not_found(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 404 from pypistats recent API raises PackageNotFoundError."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            status_code=404,
            json={"message": "Not Found"},
        )

        with pytest.raises(PackageNotFoundError) as exc_info:
            fetch_pypi_stats("requests", period_days=30)

        assert exc_info.value.status_code == 404

    def test_pypi_metadata_500_raises_fetch_error(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 500 from PyPI metadata API raises FetchError (not PackageNotFoundError)."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            status_code=500,
            text="Internal Server Error",
        )

        with pytest.raises(FetchError) as exc_info:
            fetch_pypi_stats("requests", period_days=30)

        assert exc_info.value.status_code == 500
        assert not isinstance(exc_info.value, PackageNotFoundError)

    def test_pypistats_500_raises_fetch_error(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 500 from pypistats raises FetchError."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            status_code=500,
            text="Server Error",
        )

        with pytest.raises(FetchError) as exc_info:
            fetch_pypi_stats("requests", period_days=30)

        assert exc_info.value.status_code == 500

    def test_pypi_metadata_429_raises_fetch_error(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 429 (rate limited) from PyPI metadata API raises FetchError."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            status_code=429,
            text="Too Many Requests",
        )

        with pytest.raises(FetchError) as exc_info:
            fetch_pypi_stats("requests", period_days=30)

        assert exc_info.value.status_code == 429

    def test_invalid_period_raises_value_error(self) -> None:
        """Invalid period_days raises ValueError before any HTTP call."""
        with pytest.raises(ValueError, match="period_days"):
            fetch_pypi_stats("requests", period_days=60)

    def test_invalid_period_7_raises_value_error(self) -> None:
        """period_days=7 raises ValueError."""
        with pytest.raises(ValueError, match="period_days"):
            fetch_pypi_stats("requests", period_days=7)

    def test_invalid_period_180_raises_value_error(self) -> None:
        """period_days=180 raises ValueError."""
        with pytest.raises(ValueError, match="period_days"):
            fetch_pypi_stats("requests", period_days=180)

    def test_empty_package_name_raises_value_error(self) -> None:
        """Empty package name raises ValueError before any HTTP call."""
        with pytest.raises(ValueError):
            fetch_pypi_stats("", period_days=30)

    def test_whitespace_package_name_raises_value_error(self) -> None:
        """Whitespace-only package name raises ValueError."""
        with pytest.raises(ValueError):
            fetch_pypi_stats("   ", period_days=30)

    def test_package_not_found_error_is_fetch_error_subclass(self, httpx_mock: HTTPXMock) -> None:
        """PackageNotFoundError is a subclass of FetchError."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/nonexistent-xyz-123/json",
            status_code=404,
            json={"message": "Not Found"},
        )

        with pytest.raises(FetchError):
            fetch_pypi_stats("nonexistent-xyz-123", period_days=30)

    def test_malformed_recent_response_raises_fetch_error(self, httpx_mock: HTTPXMock) -> None:
        """Malformed pypistats response raises FetchError."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json={"unexpected": "structure"},  # missing 'data.last_month'
        )

        with pytest.raises(FetchError):
            fetch_pypi_stats("requests", period_days=30)


# ---------------------------------------------------------------------------
# npm fetcher — happy path tests
# ---------------------------------------------------------------------------

class TestFetchNpmStats:
    """Tests for fetch_npm_stats."""

    def test_365_day_period(self, httpx_mock: HTTPXMock) -> None:
        """365-day period uses last-year endpoint with scale factor 1."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            json=_npm_downloads_body(downloads=500_000_000),
        )

        stats = fetch_npm_stats("lodash", period_days=365)

        assert stats.package_name == "lodash"
        assert stats.registry == Registry.NPM
        assert stats.total_downloads == 500_000_000
        assert stats.period_days == 365

    def test_30_day_period(self, httpx_mock: HTTPXMock) -> None:
        """30-day period uses last-month endpoint with scale factor 1."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_MONTH_URL,
            json=_npm_downloads_body(downloads=40_000_000),
        )

        stats = fetch_npm_stats("lodash", period_days=30)

        assert stats.total_downloads == 40_000_000
        assert stats.period_days == 30

    def test_90_day_period_triples_monthly(self, httpx_mock: HTTPXMock) -> None:
        """90-day period fetches last-month and multiplies by 3."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_MONTH_URL,
            json=_npm_downloads_body(downloads=10_000_000),
        )

        stats = fetch_npm_stats("lodash", period_days=90)

        assert stats.total_downloads == 30_000_000
        assert stats.period_days == 90

    def test_metadata_fields_populated(self, httpx_mock: HTTPXMock) -> None:
        """Description, version, and homepage are parsed from npm metadata."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(
                description="Lodash modular utilities",
                version="4.17.21",
                homepage="https://lodash.com",
            ),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            json=_npm_downloads_body(),
        )

        stats = fetch_npm_stats("lodash", period_days=365)

        assert stats.description == "Lodash modular utilities"
        assert stats.version == "4.17.21"
        assert stats.homepage == "https://lodash.com"

    def test_homepage_fallback_to_repo_url(self, httpx_mock: HTTPXMock) -> None:
        """Falls back to repository.url if homepage is absent."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json={
                "name": "lodash",
                "description": "Lodash",
                "version": "4.17.21",
                "repository": {
                    "type": "git",
                    "url": "git+https://github.com/lodash/lodash.git",
                },
            },
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            json=_npm_downloads_body(),
        )

        stats = fetch_npm_stats("lodash", period_days=365)
        # git+ and .git suffixes should be stripped
        assert stats.homepage is not None
        assert "git+" not in stats.homepage
        assert stats.homepage.endswith(".git") is False

    def test_homepage_fallback_strips_git_prefix(self, httpx_mock: HTTPXMock) -> None:
        """git+ prefix is stripped from repository URL."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json={
                "name": "lodash",
                "version": "4.17.21",
                "repository": {
                    "type": "git",
                    "url": "git+https://github.com/lodash/lodash.git",
                },
            },
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            json=_npm_downloads_body(),
        )

        stats = fetch_npm_stats("lodash", period_days=365)
        assert stats.homepage == "https://github.com/lodash/lodash"

    def test_missing_optional_metadata_is_none(self, httpx_mock: HTTPXMock) -> None:
        """Missing optional metadata fields resolve to None."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json={"name": "lodash", "version": "4.17.21"},
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            json=_npm_downloads_body(),
        )

        stats = fetch_npm_stats("lodash", period_days=365)
        assert stats.description is None
        assert stats.homepage is None

    def test_zero_downloads(self, httpx_mock: HTTPXMock) -> None:
        """Zero downloads from API returns a valid stats object with 0."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            json=_npm_downloads_body(downloads=0),
        )

        stats = fetch_npm_stats("lodash", period_days=365)
        assert stats.total_downloads == 0

    def test_90_day_returns_triple_monthly_count(self, httpx_mock: HTTPXMock) -> None:
        """90-day scale factor is exactly 3."""
        monthly = 7_777_777
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_MONTH_URL,
            json=_npm_downloads_body(downloads=monthly),
        )

        stats = fetch_npm_stats("lodash", period_days=90)
        assert stats.total_downloads == monthly * 3

    def test_version_parsed_correctly(self, httpx_mock: HTTPXMock) -> None:
        """Package version is parsed from npm metadata."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(version="5.0.0-beta.1"),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            json=_npm_downloads_body(),
        )

        stats = fetch_npm_stats("lodash", period_days=365)
        assert stats.version == "5.0.0-beta.1"


# ---------------------------------------------------------------------------
# npm fetcher — error handling tests
# ---------------------------------------------------------------------------

class TestFetchNpmStatsErrors:
    """Error handling tests for fetch_npm_stats."""

    def test_metadata_404_raises_package_not_found(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 404 from npm registry raises PackageNotFoundError."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            status_code=404,
            json={"error": "Not found"},
        )

        with pytest.raises(PackageNotFoundError) as exc_info:
            fetch_npm_stats("lodash", period_days=365)

        assert exc_info.value.registry == Registry.NPM
        assert exc_info.value.status_code == 404

    def test_downloads_404_raises_package_not_found(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 404 from npm Downloads API raises PackageNotFoundError."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            status_code=404,
            json={"error": "not found"},
        )

        with pytest.raises(PackageNotFoundError) as exc_info:
            fetch_npm_stats("lodash", period_days=365)

        assert exc_info.value.status_code == 404

    def test_metadata_500_raises_fetch_error(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 500 from npm registry raises FetchError (not PackageNotFoundError)."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            status_code=500,
            text="Server Error",
        )

        with pytest.raises(FetchError) as exc_info:
            fetch_npm_stats("lodash", period_days=365)

        assert exc_info.value.status_code == 500
        assert not isinstance(exc_info.value, PackageNotFoundError)

    def test_downloads_500_raises_fetch_error(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 500 from npm Downloads API raises FetchError."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            status_code=500,
            text="Server Error",
        )

        with pytest.raises(FetchError) as exc_info:
            fetch_npm_stats("lodash", period_days=365)

        assert exc_info.value.status_code == 500

    def test_downloads_429_raises_fetch_error(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 429 (rate limited) from npm Downloads API raises FetchError."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            status_code=429,
            text="Too Many Requests",
        )

        with pytest.raises(FetchError) as exc_info:
            fetch_npm_stats("lodash", period_days=365)

        assert exc_info.value.status_code == 429

    def test_invalid_period_raises_value_error(self) -> None:
        """Invalid period_days raises ValueError before any HTTP call."""
        with pytest.raises(ValueError, match="period_days"):
            fetch_npm_stats("lodash", period_days=7)

    def test_invalid_period_60_raises_value_error(self) -> None:
        """period_days=60 raises ValueError."""
        with pytest.raises(ValueError, match="period_days"):
            fetch_npm_stats("lodash", period_days=60)

    def test_empty_package_name_raises_value_error(self) -> None:
        """Empty package name raises ValueError before any HTTP call."""
        with pytest.raises(ValueError):
            fetch_npm_stats("", period_days=30)

    def test_whitespace_package_name_raises_value_error(self) -> None:
        """Whitespace-only package name raises ValueError."""
        with pytest.raises(ValueError):
            fetch_npm_stats("   ", period_days=30)

    def test_package_not_found_is_fetch_error_subclass(self, httpx_mock: HTTPXMock) -> None:
        """PackageNotFoundError is a subclass of FetchError."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            status_code=404,
            json={"error": "Not found"},
        )

        with pytest.raises(FetchError):
            fetch_npm_stats("lodash", period_days=365)

    def test_malformed_downloads_response_raises_fetch_error(self, httpx_mock: HTTPXMock) -> None:
        """Malformed npm downloads response raises FetchError."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            json={"unexpected": "structure"},  # missing 'downloads' key
        )

        with pytest.raises(FetchError):
            fetch_npm_stats("lodash", period_days=365)


# ---------------------------------------------------------------------------
# Scoped npm package tests
# ---------------------------------------------------------------------------

class TestScopedNpmPackage:
    """Tests for scoped npm packages (e.g. @babel/core)."""

    _METADATA_URL = "https://registry.npmjs.org/%40babel%2Fcore/latest"
    _DOWNLOADS_YEAR_URL = "https://api.npmjs.org/downloads/point/last-year/%40babel%2Fcore"
    _DOWNLOADS_MONTH_URL = "https://api.npmjs.org/downloads/point/last-month/%40babel%2Fcore"

    def test_scoped_package_365_days(self, httpx_mock: HTTPXMock) -> None:
        """Scoped package name is URL-encoded in API requests."""
        httpx_mock.add_response(
            url=self._METADATA_URL,
            json={
                "name": "@babel/core",
                "description": "Babel compiler core",
                "version": "7.22.0",
                "homepage": "https://babel.dev/docs/en/babel-core",
            },
        )
        httpx_mock.add_response(
            url=self._DOWNLOADS_YEAR_URL,
            json={"downloads": 200_000_000, "package": "@babel/core"},
        )

        stats = fetch_npm_stats("@babel/core", period_days=365)

        assert stats.package_name == "@babel/core"
        assert stats.total_downloads == 200_000_000
        assert stats.description == "Babel compiler core"
        assert stats.version == "7.22.0"

    def test_scoped_package_30_days(self, httpx_mock: HTTPXMock) -> None:
        """Scoped package 30-day period uses encoded URL and last-month endpoint."""
        httpx_mock.add_response(
            url=self._METADATA_URL,
            json={
                "name": "@babel/core",
                "version": "7.22.0",
            },
        )
        httpx_mock.add_response(
            url=self._DOWNLOADS_MONTH_URL,
            json={"downloads": 15_000_000, "package": "@babel/core"},
        )

        stats = fetch_npm_stats("@babel/core", period_days=30)

        assert stats.total_downloads == 15_000_000
        assert stats.period_days == 30

    def test_scoped_package_90_days_triples(self, httpx_mock: HTTPXMock) -> None:
        """Scoped package 90-day period fetches last-month and multiplies by 3."""
        httpx_mock.add_response(
            url=self._METADATA_URL,
            json={
                "name": "@babel/core",
                "version": "7.22.0",
            },
        )
        httpx_mock.add_response(
            url=self._DOWNLOADS_MONTH_URL,
            json={"downloads": 5_000_000, "package": "@babel/core"},
        )

        stats = fetch_npm_stats("@babel/core", period_days=90)

        assert stats.total_downloads == 15_000_000

    def test_scoped_package_with_dashes(self, httpx_mock: HTTPXMock) -> None:
        """Scoped package with dashes in org/name are correctly encoded."""
        encoded_url = "https://registry.npmjs.org/%40my-org%2Fmy-package/latest"
        downloads_url = "https://api.npmjs.org/downloads/point/last-year/%40my-org%2Fmy-package"

        httpx_mock.add_response(
            url=encoded_url,
            json={
                "name": "@my-org/my-package",
                "version": "1.0.0",
            },
        )
        httpx_mock.add_response(
            url=downloads_url,
            json={"downloads": 1_000_000, "package": "@my-org/my-package"},
        )

        stats = fetch_npm_stats("@my-org/my-package", period_days=365)
        assert stats.package_name == "@my-org/my-package"
        assert stats.total_downloads == 1_000_000


# ---------------------------------------------------------------------------
# fetch_package_stats dispatcher tests
# ---------------------------------------------------------------------------

class TestFetchPackageStats:
    """Tests for the unified fetch_package_stats dispatcher."""

    def test_dispatches_to_pypi(self, httpx_mock: HTTPXMock) -> None:
        """Registry.PYPI dispatches to the PyPI fetcher."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(last_month=1_000_000),
        )

        stats = fetch_package_stats("requests", Registry.PYPI, period_days=30)

        assert stats.registry == Registry.PYPI
        assert stats.total_downloads == 1_000_000
        assert stats.package_name == "requests"

    def test_dispatches_to_npm(self, httpx_mock: HTTPXMock) -> None:
        """Registry.NPM dispatches to the npm fetcher."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            json=_npm_downloads_body(downloads=50_000_000),
        )

        stats = fetch_package_stats("lodash", Registry.NPM, period_days=365)

        assert stats.registry == Registry.NPM
        assert stats.total_downloads == 50_000_000

    def test_pypi_365_day_period(self, httpx_mock: HTTPXMock) -> None:
        """fetch_package_stats with Registry.PYPI and 365-day period."""
        last_month = 4_000_000
        expected = int(last_month * (365 / 30))

        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(last_month=last_month),
        )

        stats = fetch_package_stats("requests", Registry.PYPI, period_days=365)
        assert stats.total_downloads == expected

    def test_npm_30_day_period(self, httpx_mock: HTTPXMock) -> None:
        """fetch_package_stats with Registry.NPM and 30-day period."""
        httpx_mock.add_response(
            url=NPM_METADATA_URL,
            json=_npm_metadata_body(),
        )
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_MONTH_URL,
            json=_npm_downloads_body(downloads=20_000_000),
        )

        stats = fetch_package_stats("lodash", Registry.NPM, period_days=30)
        assert stats.total_downloads == 20_000_000
        assert stats.period_days == 30

    def test_invalid_period_raises_value_error(self) -> None:
        """Invalid period_days raises ValueError."""
        with pytest.raises(ValueError):
            fetch_package_stats("requests", Registry.PYPI, period_days=180)

    def test_invalid_period_npm_raises_value_error(self) -> None:
        """Invalid period_days for npm raises ValueError."""
        with pytest.raises(ValueError):
            fetch_package_stats("lodash", Registry.NPM, period_days=14)

    def test_pypi_404_propagates(self, httpx_mock: HTTPXMock) -> None:
        """PackageNotFoundError from PyPI propagates through dispatcher."""
        httpx_mock.add_response(
            url="https://pypi.org/pypi/nonexistent/json",
            status_code=404,
            json={"message": "Not Found"},
        )

        with pytest.raises(PackageNotFoundError):
            fetch_package_stats("nonexistent", Registry.PYPI, period_days=30)

    def test_npm_404_propagates(self, httpx_mock: HTTPXMock) -> None:
        """PackageNotFoundError from npm propagates through dispatcher."""
        httpx_mock.add_response(
            url="https://registry.npmjs.org/nonexistent-pkg-xyz/latest",
            status_code=404,
            json={"error": "Not found"},
        )

        with pytest.raises(PackageNotFoundError):
            fetch_package_stats("nonexistent-pkg-xyz", Registry.NPM, period_days=365)


# ---------------------------------------------------------------------------
# _encode_npm_package_name tests
# ---------------------------------------------------------------------------

class TestEncodeNpmPackageName:
    """Unit tests for the npm package name URL encoder."""

    def test_plain_package_unchanged(self) -> None:
        assert _encode_npm_package_name("lodash") == "lodash"

    def test_scoped_package_encoded(self) -> None:
        assert _encode_npm_package_name("@babel/core") == "%40babel%2Fcore"

    def test_scoped_with_dashes(self) -> None:
        assert _encode_npm_package_name("@my-org/my-package") == "%40my-org%2Fmy-package"

    def test_non_scoped_with_dashes(self) -> None:
        assert _encode_npm_package_name("react-dom") == "react-dom"

    def test_empty_string(self) -> None:
        assert _encode_npm_package_name("") == ""

    def test_scoped_at_replaced(self) -> None:
        result = _encode_npm_package_name("@types/node")
        assert result.startswith("%40")
        assert "@" not in result

    def test_scoped_slash_replaced(self) -> None:
        result = _encode_npm_package_name("@types/node")
        assert "%2F" in result
        assert "/" not in result

    def test_plain_package_with_numbers(self) -> None:
        assert _encode_npm_package_name("package123") == "package123"

    def test_plain_package_with_dots(self) -> None:
        assert _encode_npm_package_name("some.package") == "some.package"

    def test_scoped_package_multiple_chars(self) -> None:
        result = _encode_npm_package_name("@angular/common")
        assert result == "%40angular%2Fcommon"


# ---------------------------------------------------------------------------
# FetchError and PackageNotFoundError tests
# ---------------------------------------------------------------------------

class TestFetchError:
    """Tests for the FetchError exception hierarchy."""

    def test_fetch_error_str_with_status(self) -> None:
        err = FetchError(
            "Something went wrong",
            package_name="requests",
            registry=Registry.PYPI,
            status_code=503,
        )
        s = str(err)
        assert "requests" in s
        assert "503" in s
        assert "Something went wrong" in s

    def test_fetch_error_str_without_status(self) -> None:
        err = FetchError(
            "Timeout occurred",
            package_name="lodash",
            registry=Registry.NPM,
        )
        s = str(err)
        assert "lodash" in s
        assert "Timeout occurred" in s

    def test_package_not_found_is_fetch_error(self) -> None:
        err = PackageNotFoundError(
            "Package not found",
            package_name="ghost-pkg",
            registry=Registry.NPM,
            status_code=404,
        )
        assert isinstance(err, FetchError)
        assert err.status_code == 404

    def test_fetch_error_attributes(self) -> None:
        err = FetchError(
            "Failed",
            package_name="mypkg",
            registry=Registry.PYPI,
            status_code=429,
        )
        assert err.package_name == "mypkg"
        assert err.registry == Registry.PYPI
        assert err.status_code == 429
        assert err.message == "Failed"

    def test_fetch_error_default_status_code_none(self) -> None:
        err = FetchError(
            "No status",
            package_name="pkg",
            registry=Registry.NPM,
        )
        assert err.status_code is None

    def test_package_not_found_attributes(self) -> None:
        err = PackageNotFoundError(
            "Not found",
            package_name="missing-pkg",
            registry=Registry.PYPI,
            status_code=404,
        )
        assert err.package_name == "missing-pkg"
        assert err.registry == Registry.PYPI
        assert err.status_code == 404
        assert err.message == "Not found"

    def test_fetch_error_registry_label_in_str(self) -> None:
        err_pypi = FetchError("err", package_name="p", registry=Registry.PYPI)
        err_npm = FetchError("err", package_name="p", registry=Registry.NPM)
        assert "pypi" in str(err_pypi).lower()
        assert "npm" in str(err_npm).lower()

    def test_package_not_found_is_exception(self) -> None:
        err = PackageNotFoundError(
            "Not found",
            package_name="pkg",
            registry=Registry.NPM,
            status_code=404,
        )
        assert isinstance(err, Exception)

    def test_fetch_error_can_be_raised_and_caught(self) -> None:
        with pytest.raises(FetchError) as exc_info:
            raise FetchError(
                "test error",
                package_name="pkg",
                registry=Registry.PYPI,
                status_code=500,
            )
        assert exc_info.value.status_code == 500

    def test_package_not_found_can_be_caught_as_fetch_error(self) -> None:
        """PackageNotFoundError should be catchable as FetchError."""
        with pytest.raises(FetchError):
            raise PackageNotFoundError(
                "not found",
                package_name="pkg",
                registry=Registry.NPM,
                status_code=404,
            )


# ---------------------------------------------------------------------------
# Additional edge-case tests
# ---------------------------------------------------------------------------

class TestPypiStatsPeriodScaling:
    """Verify period scaling arithmetic for PyPI fetcher."""

    def test_30_day_to_90_day_ratio(self, httpx_mock: HTTPXMock) -> None:
        """90-day result should be 3× the 30-day result (using same monthly base)."""
        last_month = 2_000_000

        # 30-day request
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(last_month=last_month),
        )
        stats_30 = fetch_pypi_stats("requests", period_days=30)

        # 90-day request
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(last_month=last_month),
        )
        stats_90 = fetch_pypi_stats("requests", period_days=90)

        assert stats_90.total_downloads == stats_30.total_downloads * 3

    def test_30_day_vs_365_day_scaling(self, httpx_mock: HTTPXMock) -> None:
        """365-day total is 365/30 × monthly total."""
        last_month = 1_000_000
        expected_365 = int(last_month * (365 / 30))

        # 365-day request
        httpx_mock.add_response(
            url="https://pypi.org/pypi/requests/json",
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url="https://pypistats.org/api/packages/requests/recent?period=month",
            json=_pypi_recent_body(last_month=last_month),
        )
        stats_365 = fetch_pypi_stats("requests", period_days=365)
        assert stats_365.total_downloads == expected_365


class TestNpmStatsPeriodScaling:
    """Verify period scaling arithmetic for npm fetcher."""

    def test_30_day_scale_factor_is_one(self, httpx_mock: HTTPXMock) -> None:
        """30-day returns exact value from API without scaling."""
        raw_downloads = 8_888_888
        httpx_mock.add_response(url=NPM_METADATA_URL, json=_npm_metadata_body())
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_MONTH_URL,
            json=_npm_downloads_body(downloads=raw_downloads),
        )
        stats = fetch_npm_stats("lodash", period_days=30)
        assert stats.total_downloads == raw_downloads

    def test_90_day_scale_factor_is_three(self, httpx_mock: HTTPXMock) -> None:
        """90-day returns 3× the monthly value."""
        raw_downloads = 3_333_333
        httpx_mock.add_response(url=NPM_METADATA_URL, json=_npm_metadata_body())
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_MONTH_URL,
            json=_npm_downloads_body(downloads=raw_downloads),
        )
        stats = fetch_npm_stats("lodash", period_days=90)
        assert stats.total_downloads == raw_downloads * 3

    def test_365_day_scale_factor_is_one(self, httpx_mock: HTTPXMock) -> None:
        """365-day returns exact value from last-year API without scaling."""
        raw_downloads = 999_000_000
        httpx_mock.add_response(url=NPM_METADATA_URL, json=_npm_metadata_body())
        httpx_mock.add_response(
            url=NPM_DOWNLOADS_YEAR_URL,
            json=_npm_downloads_body(downloads=raw_downloads),
        )
        stats = fetch_npm_stats("lodash", period_days=365)
        assert stats.total_downloads == raw_downloads
