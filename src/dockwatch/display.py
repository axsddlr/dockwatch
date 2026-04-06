"""Rich rendering helpers for dockwatch CLI output."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .models import ContainerInfo, UpdateResult

console = Console()


def render_containers_table(containers: list[ContainerInfo]) -> None:
    table = Table(title="Running Containers")
    table.add_column("Name", style="cyan")
    table.add_column("Image")
    table.add_column("Tag")
    table.add_column("Registry")

    for container in containers:
        table.add_row(
            container.name or "-",
            container.image_ref or "-",
            container.current_tag or "-",
            container.registry.value,
        )

    if not containers:
        table.add_row("-", "No running containers", "-", "-")

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
    table.add_column("Current")
    table.add_column("Latest")
    table.add_column("Status")

    for result in results:
        status, color = _status_label(result)
        latest_display = result.latest_tag or "-"
        if result.status == "PINNED":
            latest_display = "Pinned by config"
        if result.check_error:
            latest_display = result.check_error
        table.add_row(
            result.container_info.name or "-",
            result.container_info.current_tag or "-",
            latest_display,
            f"[{color}]{status}[/{color}]",
        )

    if not results:
        table.add_row("-", "-", "No results", "[yellow]UNKNOWN[/yellow]")

    console.print(table)


def render_summary(results: list[UpdateResult]) -> None:
    outdated = sum(1 for result in results if result.is_outdated is True and not result.check_error)
    up_to_date = sum(1 for result in results if result.is_outdated is False and not result.check_error)
    unknown = len(results) - outdated - up_to_date
    console.print(f"Summary: {outdated} outdated, {up_to_date} up-to-date, {unknown} unknown")
