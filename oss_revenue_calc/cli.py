"""Typer-based CLI entry point for oss_revenue_calc.

Defines all CLI commands, options, and their help text. The main commands are:

- ``calculate`` — fetch stats and compute revenue estimates for a package.
- ``platforms`` — list all built-in AI coding platform configurations.
- ``version``   — print the installed tool version.

Example usage (shell)::

    oss-revenue-calc calculate requests --platform copilot --ai-share 0.30
    oss-revenue-calc calculate lodash --registry npm --all-platforms
    oss-revenue-calc platforms
    oss-revenue-calc version
"""

from __future__ import annotations

import sys
from enum import Enum
from typing import Optional

import typer
from rich.console import Console
from rich.text import Text

from oss_revenue_calc import __version__
from oss_revenue_calc.calculator import (
    calculate_revenue,
    calculate_revenue_for_platforms,
)
from oss_revenue_calc.fetcher import (
    FetchError,
    PackageNotFoundError,
    fetch_package_stats,
)
from oss_revenue_calc.models import (
    OutputFormat,
    Registry,
    RevenueModel,
)
from oss_revenue_calc.platforms import (
    ALL_PLATFORMS,
    build_custom_platform,
    get_platform,
    list_platforms,
)
from oss_revenue_calc.report import (
    export_csv,
    export_json,
    render_multi_platform_report,
    render_platforms_table,
    render_terminal_report,
)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="oss-revenue-calc",
    help=(
        "Calculate theoretical revenue owed to OSS maintainers under the "
        "'Spotify model' for AI coding platforms.\n\n"
        "Fetches real download stats from PyPI / npm and runs configurable "
        "revenue-share models to produce fair-compensation estimates."
    ),
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=True,
)

_console = Console()
_err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Enum wrappers for Typer (Typer needs plain Enum subclasses for choices)
# ---------------------------------------------------------------------------

class RegistryChoice(str, Enum):
    """Registry choices for the CLI."""
    pypi = "pypi"
    npm = "npm"


class OutputFormatChoice(str, Enum):
    """Output format choices for the CLI."""
    terminal = "terminal"
    json = "json"
    csv = "csv"


class RevenueModelChoice(str, Enum):
    """Revenue model choices for the CLI."""
    prorata = "prorata"
    peruse = "peruse"
    both = "both"


# ---------------------------------------------------------------------------
# calculate command
# ---------------------------------------------------------------------------

@app.command(name="calculate")
def calculate_command(
    package: str = typer.Argument(
        ...,
        help="Package name to analyse (e.g. [cyan]requests[/cyan] or [cyan]lodash[/cyan]).",
        metavar="PACKAGE",
    ),
    registry: RegistryChoice = typer.Option(
        RegistryChoice.pypi,
        "--registry", "-r",
        help="Package registry to query ([cyan]pypi[/cyan] or [cyan]npm[/cyan]).",
        show_default=True,
    ),
    platform: Optional[str] = typer.Option(
        "copilot",
        "--platform", "-p",
        help=(
            "AI platform preset slug (e.g. [cyan]copilot[/cyan], "
            "[cyan]cursor[/cyan], [cyan]tabnine[/cyan]). "
            "Use [cyan]--all-platforms[/cyan] to run all. "
            "Use [cyan]custom[/cyan] with [cyan]--subscribers[/cyan] / "
            "[cyan]--arpu[/cyan] for a custom platform."
        ),
        show_default=True,
    ),
    all_platforms: bool = typer.Option(
        False,
        "--all-platforms",
        help="Run estimates for all built-in platforms and display a comparison table.",
        is_flag=True,
    ),
    ai_share: float = typer.Option(
        0.30,
        "--ai-share",
        help=(
            "Fraction of downloads attributed to AI-assisted coding (0.0–1.0). "
            "E.g. [cyan]0.30[/cyan] means 30%% of downloads are AI-driven."
        ),
        show_default=True,
        min=0.0,
        max=1.0,
    ),
    subscribers: Optional[int] = typer.Option(
        None,
        "--subscribers",
        help="Override subscriber count for the selected platform.",
        min=0,
    ),
    arpu: Optional[float] = typer.Option(
        None,
        "--arpu",
        help="Override monthly average revenue per user (USD) for the selected platform.",
        min=0.0,
    ),
    revenue_share_pct: Optional[float] = typer.Option(
        None,
        "--revenue-share-pct",
        help=(
            "Override OSS revenue share fraction for the selected platform "
            "(0.0–1.0). E.g. [cyan]0.05[/cyan] for 5%%."
        ),
        min=0.0,
        max=1.0,
    ),
    period: int = typer.Option(
        365,
        "--period",
        help="Download period in days. Must be [cyan]30[/cyan], [cyan]90[/cyan], or [cyan]365[/cyan].",
        show_default=True,
    ),
    output: OutputFormatChoice = typer.Option(
        OutputFormatChoice.terminal,
        "--output", "-o",
        help="Output format: [cyan]terminal[/cyan] (Rich), [cyan]json[/cyan], or [cyan]csv[/cyan].",
        show_default=True,
    ),
    model: RevenueModelChoice = typer.Option(
        RevenueModelChoice.both,
        "--model",
        help="Revenue model(s) to compute: [cyan]prorata[/cyan], [cyan]peruse[/cyan], or [cyan]both[/cyan].",
        show_default=True,
    ),
) -> None:
    """Calculate revenue estimates for a package.

    Fetches real download statistics from PyPI or npm, then runs the selected
    revenue-share model(s) against the chosen AI coding platform(s).

    [bold]Examples:[/bold]

      [cyan]oss-revenue-calc calculate requests --platform copilot --ai-share 0.30[/cyan]

      [cyan]oss-revenue-calc calculate numpy --all-platforms --ai-share 0.40[/cyan]

      [cyan]oss-revenue-calc calculate lodash --registry npm --platform cursor[/cyan]

      [cyan]oss-revenue-calc calculate flask --output json --platform copilot[/cyan]
    """
    # ------------------------------------------------------------------
    # Validate period
    # ------------------------------------------------------------------
    if period not in {30, 90, 365}:
        _err_console.print(
            f"[bold red]Error:[/bold red] --period must be 30, 90, or 365; got {period}."
        )
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Map CLI enums to model enums
    # ------------------------------------------------------------------
    registry_enum = Registry(registry.value)
    revenue_model_enum = RevenueModel(model.value)

    # ------------------------------------------------------------------
    # Resolve platform(s)
    # ------------------------------------------------------------------
    if all_platforms:
        platforms_to_run = list_platforms()
        # Apply overrides to each platform if provided
        if any(v is not None for v in (subscribers, arpu, revenue_share_pct)):
            platforms_to_run = [
                p.with_overrides(
                    subscribers=subscribers,
                    monthly_arpu=arpu,
                    oss_revenue_share=revenue_share_pct,
                )
                for p in platforms_to_run
            ]
    else:
        platform_slug = (platform or "copilot").lower().strip()

        if platform_slug == "custom":
            # Build a custom platform — require subscribers and arpu
            if subscribers is None or arpu is None:
                _err_console.print(
                    "[bold red]Error:[/bold red] When using [cyan]--platform custom[/cyan] "
                    "you must provide [cyan]--subscribers[/cyan] and [cyan]--arpu[/cyan]."
                )
                raise typer.Exit(code=1)

            try:
                resolved_platform = build_custom_platform(
                    subscribers=subscribers,
                    monthly_arpu=arpu,
                    oss_revenue_share=(
                        revenue_share_pct if revenue_share_pct is not None else 0.05
                    ),
                )
            except ValueError as exc:
                _err_console.print(
                    f"[bold red]Error building custom platform:[/bold red] {exc}"
                )
                raise typer.Exit(code=1)
        else:
            resolved_platform = get_platform(platform_slug)
            if resolved_platform is None:
                available = ", ".join(sorted(ALL_PLATFORMS.keys()))
                _err_console.print(
                    f"[bold red]Error:[/bold red] Unknown platform [cyan]{platform_slug!r}[/cyan]. "
                    f"Available: [cyan]{available}[/cyan], custom"
                )
                raise typer.Exit(code=1)

            # Apply any CLI overrides
            if any(v is not None for v in (subscribers, arpu, revenue_share_pct)):
                resolved_platform = resolved_platform.with_overrides(
                    subscribers=subscribers,
                    monthly_arpu=arpu,
                    oss_revenue_share=revenue_share_pct,
                )

        platforms_to_run = [resolved_platform]

    # ------------------------------------------------------------------
    # Fetch package stats
    # ------------------------------------------------------------------
    if output == OutputFormatChoice.terminal:
        _console.print(
            f"\n[dim]Fetching {registry_enum.value.upper()} stats for "
            f"[cyan]{package}[/cyan] ({period} days)…[/dim]"
        )

    try:
        stats = fetch_package_stats(
            package_name=package,
            registry=registry_enum,
            period_days=period,
        )
    except PackageNotFoundError as exc:
        _err_console.print(
            f"[bold red]Package not found:[/bold red] {exc}"
        )
        raise typer.Exit(code=1)
    except FetchError as exc:
        _err_console.print(
            f"[bold red]Fetch error:[/bold red] {exc}\n"
            "[dim]Check your internet connection and try again.[/dim]"
        )
        raise typer.Exit(code=1)
    except ValueError as exc:
        _err_console.print(
            f"[bold red]Input error:[/bold red] {exc}"
        )
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Run calculations
    # ------------------------------------------------------------------
    results = calculate_revenue_for_platforms(
        package_stats=stats,
        platforms=platforms_to_run,
        ai_share=ai_share,
        model=revenue_model_enum,
    )

    # ------------------------------------------------------------------
    # Render output
    # ------------------------------------------------------------------
    if output == OutputFormatChoice.json:
        print(export_json(results))
        return

    if output == OutputFormatChoice.csv:
        print(export_csv(results), end="")
        return

    # Terminal output
    if all_platforms or len(results) > 1:
        render_multi_platform_report(results, console=_console)
    else:
        render_terminal_report(results[0], console=_console)


# ---------------------------------------------------------------------------
# platforms command
# ---------------------------------------------------------------------------

@app.command(name="platforms")
def platforms_command() -> None:
    """List all built-in AI coding platform configurations.

    Displays a table with subscriber counts, pricing, and OSS pool estimates
    for each platform preset.

    [bold]Example:[/bold]

      [cyan]oss-revenue-calc platforms[/cyan]
    """
    render_platforms_table(list_platforms(), console=_console)


# ---------------------------------------------------------------------------
# version command
# ---------------------------------------------------------------------------

@app.command(name="version")
def version_command() -> None:
    """Print the installed version of oss-revenue-calc.

    [bold]Example:[/bold]

      [cyan]oss-revenue-calc version[/cyan]
    """
    _console.print(
        f"[bold cyan]oss-revenue-calc[/bold cyan] version [bold]{__version__}[/bold]"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point for the oss-revenue-calc CLI.

    This function is called by the ``oss-revenue-calc`` console script
    defined in ``pyproject.toml``.
    """
    app()


if __name__ == "__main__":
    main()
