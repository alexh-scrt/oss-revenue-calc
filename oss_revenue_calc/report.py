"""Rich-powered report rendering and data export for oss_revenue_calc.

Provides functions to render formatted terminal reports using Rich and to
export results to JSON or CSV format. All public functions accept a
:class:`~oss_revenue_calc.models.RevenueResult` or a list thereof.

Example usage::

    from oss_revenue_calc.report import render_terminal_report, export_json, export_csv
    from oss_revenue_calc.calculator import calculate_revenue

    result = calculate_revenue(stats, platform, ai_share=0.30)
    render_terminal_report(result)
    print(export_json([result]))
    print(export_csv([result]))
"""

from __future__ import annotations

import csv
import io
import json
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import print as rprint

from oss_revenue_calc.models import (
    ModelResult,
    PlatformConfig,
    RevenueModel,
    RevenueResult,
)

# ---------------------------------------------------------------------------
# Console singleton used for all Rich output
# ---------------------------------------------------------------------------

_console = Console()


# ---------------------------------------------------------------------------
# Terminal report rendering
# ---------------------------------------------------------------------------

def render_terminal_report(
    result: RevenueResult,
    console: Optional[Console] = None,
) -> None:
    """Render a Rich-formatted revenue estimate report to the terminal.

    Displays a full breakdown including package stats, platform configuration,
    revenue model estimates, and key assumptions.

    Args:
        result: The :class:`~oss_revenue_calc.models.RevenueResult` to render.
        console: Optional :class:`rich.console.Console` instance. Defaults to
            the module-level console.
    """
    con = console or _console

    stats = result.package_stats
    platform = result.platform

    # -----------------------------------------------------------------------
    # Header panel
    # -----------------------------------------------------------------------
    title_text = Text(justify="center")
    title_text.append("OSS Revenue Estimate: ", style="bold white")
    title_text.append(stats.package_name, style="bold cyan")
    title_text.append(f" ({stats.registry_display})", style="dim white")

    con.print()
    con.print(Panel(title_text, box=box.ROUNDED, border_style="cyan", padding=(0, 2)))
    con.print()

    # -----------------------------------------------------------------------
    # Package stats section
    # -----------------------------------------------------------------------
    con.print("[bold yellow]📦 Package Stats[/bold yellow]", end="")
    if stats.period_days:
        con.print(f" [dim](last {stats.period_days} days)[/dim]")
    else:
        con.print()

    ai_downloads = result.ai_attributed_downloads
    ai_pct = result.ai_share * 100

    stats_table = Table.grid(padding=(0, 2))
    stats_table.add_column(style="dim", min_width=22)
    stats_table.add_column(style="white")

    stats_table.add_row("Registry:", stats.registry_display)
    stats_table.add_row("Package:", stats.package_name)
    if stats.version:
        stats_table.add_row("Latest Version:", stats.version)
    if stats.description:
        desc = stats.description[:80] + "…" if len(stats.description or "") > 80 else (stats.description or "")
        stats_table.add_row("Description:", desc)
    stats_table.add_row(
        "Total Downloads:",
        f"[bold]{stats.total_downloads:,}[/bold]",
    )
    stats_table.add_row(
        "AI-Attributed:",
        f"[bold green]{ai_downloads:,}[/bold green]  "
        f"[dim]({ai_pct:.1f}% of total)[/dim]",
    )
    stats_table.add_row("Period:", f"{stats.period_days} days")
    if stats.homepage:
        stats_table.add_row("Homepage:", f"[link={stats.homepage}]{stats.homepage}[/link]")

    con.print(stats_table)
    con.print()

    # -----------------------------------------------------------------------
    # Platform section
    # -----------------------------------------------------------------------
    con.print(f"[bold yellow]🤖 Platform: {platform.name}[/bold yellow]")

    platform_table = Table.grid(padding=(0, 2))
    platform_table.add_column(style="dim", min_width=22)
    platform_table.add_column(style="white")

    platform_table.add_row("Subscribers:", f"{platform.subscribers:,}")
    platform_table.add_row("Monthly ARPU:", f"${platform.monthly_arpu:,.2f}")
    platform_table.add_row(
        "Annual Revenue:",
        f"[bold]${platform.annual_revenue:,.0f}[/bold]",
    )
    platform_table.add_row(
        f"OSS Pool ({platform.oss_revenue_share * 100:.0f}%):",
        f"[bold green]${platform.annual_oss_pool:,.0f}[/bold green]",
    )
    if platform.source_url:
        platform_table.add_row(
            "Source:",
            f"[dim][link={platform.source_url}]{platform.source_url}[/link][/dim]",
        )

    con.print(platform_table)
    con.print()

    # -----------------------------------------------------------------------
    # Revenue estimates table
    # -----------------------------------------------------------------------
    con.print("[bold yellow]💰 Revenue Estimates[/bold yellow]")

    rev_table = Table(
        box=box.SIMPLE_HEAD,
        border_style="dim",
        show_header=True,
        header_style="bold white",
        padding=(0, 1),
    )
    rev_table.add_column("Model", style="cyan", min_width=18)
    rev_table.add_column("Annual", style="bold green", justify="right", min_width=14)
    rev_table.add_column("Monthly", style="green", justify="right", min_width=14)

    for model_result in result.model_results:
        model_label = _model_display_name(model_result.model)
        rev_table.add_row(
            model_label,
            f"${model_result.annual_revenue_usd:,.2f}",
            f"${model_result.monthly_revenue_usd:,.2f}",
        )

    if len(result.model_results) > 1:
        rev_table.add_section()
        rev_table.add_row(
            "[bold]Average[/bold]",
            f"[bold]${result.average_annual_revenue:,.2f}[/bold]",
            f"[bold]${result.average_monthly_revenue:,.2f}[/bold]",
        )

    con.print(rev_table)
    con.print()

    # -----------------------------------------------------------------------
    # Assumptions section
    # -----------------------------------------------------------------------
    con.print("[bold yellow]📊 Assumptions[/bold yellow]")

    assume_table = Table.grid(padding=(0, 2))
    assume_table.add_column(style="dim", min_width=30)
    assume_table.add_column(style="white")

    assume_table.add_row("AI download share:", f"{result.ai_share * 100:.1f}%")
    if result.package_download_share is not None:
        assume_table.add_row(
            "Package share of platform downloads:",
            f"{result.package_download_share * 100:.4f}%",
        )
    assume_table.add_row(
        "Downloads per subscriber per month:",
        f"{platform.downloads_per_subscriber_per_month:,.0f}",
    )

    con.print(assume_table)
    con.print()

    # -----------------------------------------------------------------------
    # Model notes (collapsible detail)
    # -----------------------------------------------------------------------
    for model_result in result.model_results:
        if model_result.notes:
            con.print(
                f"[dim]  {_model_display_name(model_result.model)}: "
                f"{model_result.notes}[/dim]"
            )

    con.print()


def render_multi_platform_report(
    results: list[RevenueResult],
    console: Optional[Console] = None,
) -> None:
    """Render a comparison table of revenue estimates across multiple platforms.

    When results for multiple platforms are available, this function renders a
    compact summary table instead of the full per-platform breakdown.

    Args:
        results: List of :class:`~oss_revenue_calc.models.RevenueResult` objects,
            typically one per platform.
        console: Optional :class:`rich.console.Console` instance.
    """
    if not results:
        return

    con = console or _console
    stats = results[0].package_stats

    # Header
    title_text = Text(justify="center")
    title_text.append("OSS Revenue Comparison: ", style="bold white")
    title_text.append(stats.package_name, style="bold cyan")
    title_text.append(f" ({stats.registry_display})", style="dim white")

    con.print()
    con.print(Panel(title_text, box=box.ROUNDED, border_style="cyan", padding=(0, 2)))
    con.print()

    # Package summary
    con.print(
        f"[bold yellow]📦 Package:[/bold yellow] [cyan]{stats.package_name}[/cyan]  "
        f"[dim]{stats.total_downloads:,} total downloads ({stats.period_days} days)[/dim]"
    )
    ai_downloads = results[0].ai_attributed_downloads
    ai_pct = results[0].ai_share * 100
    con.print(
        f"[bold yellow]🤖 AI Share:[/bold yellow] "
        f"[green]{ai_pct:.1f}%[/green]  "
        f"[dim]({ai_downloads:,} AI-attributed downloads / year)[/dim]"
    )
    con.print()

    # Comparison table
    table = Table(
        box=box.ROUNDED,
        border_style="dim",
        show_header=True,
        header_style="bold white",
        padding=(0, 1),
        title="[bold]Revenue Estimates by Platform[/bold]",
        title_style="yellow",
    )
    table.add_column("Platform", style="cyan", min_width=24)
    table.add_column("Subscribers", justify="right", style="dim")
    table.add_column("OSS Pool/yr", justify="right", style="dim")
    table.add_column("Pro-Rata/yr", justify="right", style="green")
    table.add_column("Per-Use/yr", justify="right", style="green")
    table.add_column("Average/yr", justify="right", style="bold green")
    table.add_column("Average/mo", justify="right", style="green")

    for result in results:
        platform = result.platform
        prorata_result = result.get_model_result(RevenueModel.PRORATA)
        peruse_result = result.get_model_result(RevenueModel.PERUSE)

        prorata_str = (
            f"${prorata_result.annual_revenue_usd:,.2f}"
            if prorata_result else "N/A"
        )
        peruse_str = (
            f"${peruse_result.annual_revenue_usd:,.2f}"
            if peruse_result else "N/A"
        )

        table.add_row(
            platform.name,
            f"{platform.subscribers:,}",
            f"${platform.annual_oss_pool:,.0f}",
            prorata_str,
            peruse_str,
            f"${result.average_annual_revenue:,.2f}",
            f"${result.average_monthly_revenue:,.2f}",
        )

    con.print(table)
    con.print()


def render_platforms_table(
    platforms: list[PlatformConfig],
    console: Optional[Console] = None,
) -> None:
    """Render a formatted table of all available platform configurations.

    Args:
        platforms: List of :class:`~oss_revenue_calc.models.PlatformConfig`
            objects to display.
        console: Optional :class:`rich.console.Console` instance.
    """
    con = console or _console

    con.print()
    con.print(
        Panel(
            "[bold white]Built-in AI Coding Platform Configurations[/bold white]",
            box=box.ROUNDED,
            border_style="cyan",
            padding=(0, 2),
        )
    )
    con.print()

    table = Table(
        box=box.ROUNDED,
        border_style="dim",
        show_header=True,
        header_style="bold white",
        padding=(0, 1),
    )
    table.add_column("Slug", style="cyan", min_width=16)
    table.add_column("Name", style="white", min_width=24)
    table.add_column("Subscribers", justify="right", style="dim")
    table.add_column("ARPU/mo", justify="right", style="dim")
    table.add_column("OSS Share", justify="right", style="dim")
    table.add_column("Annual Revenue", justify="right", style="dim")
    table.add_column("Annual OSS Pool", justify="right", style="bold green")

    for platform in platforms:
        table.add_row(
            platform.slug,
            platform.name,
            f"{platform.subscribers:,}",
            f"${platform.monthly_arpu:.2f}",
            f"{platform.oss_revenue_share * 100:.1f}%",
            f"${platform.annual_revenue:,.0f}",
            f"${platform.annual_oss_pool:,.0f}",
        )

    con.print(table)
    con.print(
        "[dim]  Note: Subscriber counts and pricing are estimates based on "
        "public reporting.\n"
        "  Use --subscribers and --arpu to override with your own research.[/dim]"
    )
    con.print()


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def export_json(
    results: list[RevenueResult],
    indent: int = 2,
) -> str:
    """Serialise a list of revenue results to a JSON string.

    Args:
        results: List of :class:`~oss_revenue_calc.models.RevenueResult` objects
            to export.
        indent: JSON indentation level. Defaults to 2.

    Returns:
        A pretty-printed JSON string containing all results.

    Example::

        json_str = export_json([result])
        with open("results.json", "w") as f:
            f.write(json_str)
    """
    data = [r.to_dict() for r in results]
    return json.dumps(data, indent=indent, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

#: Column headers for the CSV export, in order.
_CSV_FIELDNAMES: list[str] = [
    "package_name",
    "registry",
    "period_days",
    "total_downloads",
    "ai_share",
    "ai_attributed_downloads",
    "package_download_share",
    "platform_name",
    "platform_slug",
    "platform_subscribers",
    "platform_monthly_arpu",
    "platform_oss_revenue_share",
    "platform_annual_revenue",
    "platform_annual_oss_pool",
    "prorata_annual_usd",
    "prorata_monthly_usd",
    "peruse_annual_usd",
    "peruse_monthly_usd",
    "average_annual_usd",
    "average_monthly_usd",
]


def export_csv(results: list[RevenueResult]) -> str:
    """Serialise a list of revenue results to a CSV string.

    Each row represents a single platform/package combination. Pro-rata and
    per-use model values are included as separate columns. Missing model values
    are represented as empty strings.

    Args:
        results: List of :class:`~oss_revenue_calc.models.RevenueResult` objects
            to export.

    Returns:
        A CSV-formatted string with a header row followed by one data row per
        result.

    Example::

        csv_str = export_csv(results)
        with open("results.csv", "w", newline="") as f:
            f.write(csv_str)
    """
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=_CSV_FIELDNAMES,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()

    for result in results:
        row = _result_to_csv_row(result)
        writer.writerow(row)

    return buf.getvalue()


def _result_to_csv_row(result: RevenueResult) -> dict:
    """Convert a :class:`~oss_revenue_calc.models.RevenueResult` to a CSV row dict.

    Args:
        result: The result to convert.

    Returns:
        A flat dictionary mapping CSV field names to values.
    """
    stats = result.package_stats
    platform = result.platform

    prorata = result.get_model_result(RevenueModel.PRORATA)
    peruse = result.get_model_result(RevenueModel.PERUSE)

    return {
        "package_name": stats.package_name,
        "registry": stats.registry.value,
        "period_days": stats.period_days,
        "total_downloads": stats.total_downloads,
        "ai_share": result.ai_share,
        "ai_attributed_downloads": result.ai_attributed_downloads,
        "package_download_share": (
            round(result.package_download_share, 8)
            if result.package_download_share is not None
            else ""
        ),
        "platform_name": platform.name,
        "platform_slug": platform.slug,
        "platform_subscribers": platform.subscribers,
        "platform_monthly_arpu": platform.monthly_arpu,
        "platform_oss_revenue_share": platform.oss_revenue_share,
        "platform_annual_revenue": round(platform.annual_revenue, 2),
        "platform_annual_oss_pool": round(platform.annual_oss_pool, 2),
        "prorata_annual_usd": (
            round(prorata.annual_revenue_usd, 4) if prorata else ""
        ),
        "prorata_monthly_usd": (
            round(prorata.monthly_revenue_usd, 4) if prorata else ""
        ),
        "peruse_annual_usd": (
            round(peruse.annual_revenue_usd, 4) if peruse else ""
        ),
        "peruse_monthly_usd": (
            round(peruse.monthly_revenue_usd, 4) if peruse else ""
        ),
        "average_annual_usd": round(result.average_annual_revenue, 4),
        "average_monthly_usd": round(result.average_monthly_revenue, 4),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _model_display_name(model: RevenueModel) -> str:
    """Return a human-readable display name for a revenue model.

    Args:
        model: The :class:`~oss_revenue_calc.models.RevenueModel` to name.

    Returns:
        A short, title-cased display string.
    """
    if model == RevenueModel.PRORATA:
        return "Pro-Rata (Spotify)"
    if model == RevenueModel.PERUSE:
        return "Per-Use (micro-payment)"
    return model.value.title()
