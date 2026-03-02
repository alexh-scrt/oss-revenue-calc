"""oss_revenue_calc - Calculate theoretical revenue owed to OSS maintainers.

This package implements the 'Spotify model' for AI coding platform revenue sharing,
allowing open source maintainers to build data-driven arguments for sustainable
funding from AI companies that benefit from their work.

Example usage::

    from oss_revenue_calc import __version__
    print(__version__)  # '0.1.0'

Or via the CLI::

    oss-revenue-calc calculate requests --platform copilot --ai-share 0.30
"""

__version__ = "0.1.0"
__author__ = "OSS Revenue Calc Contributors"
__license__ = "MIT"

__all__ = ["__version__", "__author__", "__license__"]
