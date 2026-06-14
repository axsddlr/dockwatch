"""Rich rendering helpers for dockwatch CLI output."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .links import build_registry_link
from .models import ContainerInfo, TrivyScanResult, UpdateResult, comparison_summary, deployed_display, deployed_display_result, remote_display

console = Console()


def _source_label(info: ContainerInfo) -> str:
    if info.source == "portainer":
        if info.environment_name:
            return f"Portainer:{info.environment_name}"
        if info.environment_id:
            return f"Portainer:{info.environment_id}"
        return "Portainer"
    return "Local"


def render_containers_table(containers: list[ContainerInfo]) -> None:
    table = Table(title="Running Containers")
    table.add_column("Name", style="cyan")
    table.add_column("Source")
    table.add_column("Image")
    table.add_column("Deployed")
    table.add_column("Registry")
    table.add_column("Link")

    for container in containers:
        registry_link = build_registry_link(container)
        link_text = registry_link[1] if registry_link else "-"
        table.add_row(
            container.name or "-",
            _source_label(container),
            container.image_ref or "-",
            deployed_display(container),
            container.registry.value,
            link_text,
        )

    if not containers:
        table.add_row("-", "-", "No running containers", "-", "-", "-")

    console.print(table)


def _status_label(result: UpdateResult) -> tuple[str, str]:
    if result.status == "PINNED":
        return "PINNED", "blue"
    if result.check_error:
        return "UNKNOWN", "yellow"
    if result.is_outdated is True:
        return "OUTDATED", "red"
    if result.is_outdated is False:
        return "UP-TO-DATE", "green"
    return "UNKNOWN", "yellow"


def _bump_label(result: UpdateResult) -> str:
    if result.version_diff is None:
        return "[dim]-[/dim]"
    bump_type = result.version_diff.bump_type
    color = {
        "MAJOR": "red",
        "MINOR": "yellow",
        "PATCH": "green",
        "PRE-RELEASE": "cyan",
        "UNKNOWN": "dim",
    }.get(bump_type, "dim")
    return f"[{color}]{bump_type}[/{color}]"


def render_update_table(results: list[UpdateResult]) -> None:
    table = Table(title="Container Update Status")
    table.add_column("Name", style="cyan")
    table.add_column("Source")
    table.add_column("Deployed")
    table.add_column("Remote")
    table.add_column("Bump")
    table.add_column("Basis")
    table.add_column("Why")
    table.add_column("Status")
    table.add_column("Link")

    for result in results:
        status, color = _status_label(result)
        remote_value = remote_display(result)
        reason_display = comparison_summary(result)
        registry_link = build_registry_link(result.container_info)
        link_text = registry_link[1] if registry_link else "-"
        table.add_row(
            result.container_info.name or "-",
            _source_label(result.container_info),
            deployed_display_result(result),
            remote_value,
            _bump_label(result),
            result.comparison_basis or "-",
            reason_display,
            f"[{color}]{status}[/{color}]",
            link_text,
        )

    if not results:
        table.add_row("-", "-", "-", "No results", "[dim]-[/dim]", "-", "-", "[yellow]UNKNOWN[/yellow]", "-")

    console.print(table)


def render_summary(results: list[UpdateResult]) -> None:
    outdated = sum(1 for result in results if result.is_outdated is True and not result.check_error)
    up_to_date = sum(1 for result in results if result.is_outdated is False and not result.check_error)
    unknown = len(results) - outdated - up_to_date
    console.print(f"Summary: {outdated} outdated, {up_to_date} up-to-date, {unknown} unknown")


def render_scan_results(scan_results: list[TrivyScanResult]) -> None:
    table = Table(title="Vulnerability Scan Results")
    table.add_column("Image", style="cyan")
    table.add_column("Critical", style="red")
    table.add_column("High", style="yellow")
    table.add_column("Medium")
    table.add_column("Low")
    table.add_column("Total")
    table.add_column("Status")

    for scan in scan_results:
        if scan.error:
            table.add_row(
                scan.image_ref,
                "-", "-", "-", "-", "-",
                f"[red]{scan.error}[/red]",
            )
        else:
            table.add_row(
                scan.image_ref,
                str(scan.critical_count),
                str(scan.high_count),
                str(scan.medium_count),
                str(scan.low_count),
                str(scan.total_count),
                "[red]VULNERABLE[/red]" if scan.total_count > 0 else "[green]CLEAN[/green]",
            )

    if not scan_results:
        table.add_row("-", "-", "-", "-", "-", "-", "No scan results")

    console.print(table)
