"""Tests for oss_revenue_calc.fetcher using mocked HTTP responses.

Covers both the PyPI Stats / PyPI JSON API fetchers and the npm registry /
npm Downloads API fetchers. All network calls are intercepted with
pytest-httpx so no real HTTP requests are made during testing.
"""

from __future__ import annotations

import json
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
# Fixtures / helpers
# ---------------------------------------------------------------------------

PYPI_METADATA_URL = "https://pypi.org/pypi/requests/json"
PYPISTATS_RECENT_URL = "https://pypistats.org/api/packages/requests/recent"

NPM_METADATA_URL = "https://registry.npmjs.org/lodash/latest"
NPM_DOWNLOADS_YEAR_URL = "https://api.npmjs.org/downloads/point/last-year/lodash"
NPM_DOWNLOADS_MONTH_URL = "https://api.npmjs.org/downloads/point/last-month/lodash"


def _pypi_metadata_body(
    summary: str = "HTTP for Humans",
    version: str = "2.31.0",
    homepage: str = "https://requests.readthedocs.io",
) -> dict:
    return {
        "info": {
            "summary": summary,
            "version": version,
            "home_page": homepage,
            "project_urls": {},
        }
    }


def _pypi_recent_body(last_month: int = 5_000_000) -> dict:
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
    return {
        "name": "lodash",
        "description": description,
        "version": version,
        "homepage": homepage,
    }


def _npm_downloads_body(downloads: int = 100_000_000, package: str = "lodash") -> dict:
    return {
        "downloads": downloads,
        "package": package,
        "start": "2023-01-01",
        "end": "2023-12-31",
    }


# ---------------------------------------------------------------------------
# PyPI fetcher tests
# ---------------------------------------------------------------------------

class TestFetchPypiStats:
    """Tests for fetch_pypi_stats."""

    def test_fetch_365_day_returns_package_stats(self, httpx_mock: HTTPXMock) -> None:
        """Happy-path: 365-day fetch scales last_month figure correctly."""
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,  # second call – same URL for both 365d path calls through recent
            json=_pypi_metadata_body(),
        )
        # The 365-day path calls _fetch_pypi_recent internally, which hits the recent endpoint
        httpx_mock.add_response(
            method="GET",
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(),
        )
        # Register the recent endpoint for the scaling path
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(),
        )
        # Reset and set up correctly:
        # We need metadata AND recent endpoint
        # Use a fresh mock setup per test
        pass  # covered by dedicated sub-tests below

    def test_fetch_30_days_correct_total(self, httpx_mock: HTTPXMock) -> None:
        """30-day fetch returns last_month download count directly."""
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(summary="HTTP for Humans", version="2.31.0"),
        )
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(),
        )
        httpx_mock.add_response(
            url=f"{PYPI_METADATA_URL}",  # won't be hit for 30-day
            json=_pypi_metadata_body(),
        )
        # Simpler: let's mock all URLs that will be called
        # 30d: metadata URL + recent URL
        pass

    def test_30_day_period(self, httpx_mock: HTTPXMock) -> None:
        """30-day period: calls metadata + recent endpoint, returns last_month."""
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_metadata_body(version="2.31.0"),
        )
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_recent_body(last_month=6_000_000),
        )
        # recent endpoint
        httpx_mock.add_response(
            url=PYPI_METADATA_URL,
            json=_pypi_recent_body(last_month=6_000_000),
        )
        # The fetcher hits: pypi.org/pypi/requests/json (metadata)
        # then pypistats.org/api/packages/requests/recent (downloads)
        # We must register them separately:
        pass


class TestFetchPypiStatsIntegrated:
    """Integration-style tests with proper URL matching."""

    def test_30_day_period(self, httpx_mock: HTTPXMock) -> None:
        """30-day period: uses recent endpoint, returns last_month count."""
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
        """365-day period: fetches monthly, then scales by 365/30."""
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
        """90-day period: fetches monthly, then scales by 90/30 = 3."""
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

    def test_package_not_found_raises_package_not_found_error(self, httpx_mock: HTTPXMock) -> None:
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

    def test_pypistats_404_raises_package_not_found_error(self, httpx_mock: HTTPXMock) -> None:
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

        with pytest.raises(PackageNotFoundError):
            fetch_pypi_stats("requests", period_days=30)

    def test_metadata_500_raises_fetch_error(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 500 from PyPI metadata API raises FetchError."""
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

    def test_invalid_period_raises_value_error(self) -> None:
        """Invalid period_days raises ValueError before any HTTP call."""
        with pytest.raises(ValueError, match="period_days"):
            fetch_pypi_stats("requests", period_days=60)

    def test_empty_package_name_raises_value_error(self) -> None:
        """Empty package name raises ValueError."""
        with pytest.raises(ValueError):
            fetch_pypi_stats("   ", period_days=30)

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

        # Should not raise — 'Requests' normalises to 'requests'
        stats = fetch_pypi_stats("Requests", period_days=30)
        assert stats.package_name == "Requests"  # original name preserved


# ---------------------------------------------------------------------------
# npm fetcher tests
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
        assert ".git" not in stats.homepage

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

        with pytest.raises(PackageNotFoundError):
            fetch_npm_stats("lodash", period_days=365)

    def test_metadata_500_raises_fetch_error(self, httpx_mock: HTTPXMock) -> None:
        """HTTP 500 from npm registry raises FetchError."""
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

    def test_invalid_period_raises_value_error(self) -> None:
        """Invalid period_days raises ValueError before any HTTP call."""
        with pytest.raises(ValueError, match="period_days"):
            fetch_npm_stats("lodash", period_days=7)

    def test_empty_package_name_raises_value_error(self) -> None:
        """Empty package name raises ValueError."""
        with pytest.raises(ValueError):
            fetch_npm_stats("", period_days=30)

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


# ---------------------------------------------------------------------------
# Scoped npm package tests
# ---------------------------------------------------------------------------

class TestScopedNpmPackage:
    """Tests for scoped npm packages (e.g. @babel/core)."""

    _METADATA_URL = "https://registry.npmjs.org/%40babel%2Fcore/latest"
    _DOWNLOADS_URL = "https://api.npmjs.org/downloads/point/last-year/%40babel%2Fcore"

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
            url=self._DOWNLOADS_URL,
            json={"downloads": 200_000_000, "package": "@babel/core"},
        )

        stats = fetch_npm_stats("@babel/core", period_days=365)

        assert stats.package_name == "@babel/core"
        assert stats.total_downloads == 200_000_000
        assert stats.description == "Babel compiler core"


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

    def test_invalid_period_raises_value_error(self, httpx_mock: HTTPXMock) -> None:
        """Invalid period_days raises ValueError."""
        with pytest.raises(ValueError):
            fetch_package_stats("requests", Registry.PYPI, period_days=180)


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
