"""Rich rendering helpers for dockwatch CLI output."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .links import build_registry_link
from .models import ContainerInfo, UpdateResult, comparison_summary, deployed_display, deployed_display_result, remote_display

console = Console()


def render_containers_table(containers: list[ContainerInfo]) -> None:
    table = Table(title="Running Containers")
    table.add_column("Name", style="cyan")
    table.add_column("Image")
    table.add_column("Deployed")
    table.add_column("Registry")
    table.add_column("Link")

    for container in containers:
        registry_link = build_registry_link(container)
        link_text = registry_link[1] if registry_link else "-"
        table.add_row(
            container.name or "-",
            container.image_ref or "-",
            deployed_display(container),
            container.registry.value,
            link_text,
        )

    if not containers:
        table.add_row("-", "No running containers", "-", "-", "-")

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


def render_update_table(results: list[UpdateResult]) -> None:
    table = Table(title="Container Update Status")
    table.add_column("Name", style="cyan")
    table.add_column("Deployed")
    table.add_column("Remote")
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
            deployed_display_result(result),
            remote_value,
            reason_display,
            f"[{color}]{status}[/{color}]",
            link_text,
        )

    if not results:
        table.add_row("-", "-", "No results", "-", "[yellow]UNKNOWN[/yellow]", "-")

    console.print(table)


def render_summary(results: list[UpdateResult]) -> None:
    outdated = sum(1 for result in results if result.is_outdated is True and not result.check_error)
    up_to_date = sum(1 for result in results if result.is_outdated is False and not result.check_error)
    unknown = len(results) - outdated - up_to_date
    console.print(f"Summary: {outdated} outdated, {up_to_date} up-to-date, {unknown} unknown")
