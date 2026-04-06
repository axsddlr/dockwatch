"""Typer CLI entrypoint for dockwatch."""

from __future__ import annotations

import asyncio

import typer

from . import __version__
from .display import render_containers_table, render_summary, render_update_table
from .docker_client import DockerConnectionError, get_running_containers
from .registry import check_all
from .web import run_web_app

app = typer.Typer(
    help=(
        "Monitor running Docker containers for available image updates.\n\n"
        "Examples:\n"
        "  dockwatch list\n"
        "  dockwatch check\n"
        "  dockwatch check --container nginx\n"
        "  dockwatch version"
    )
)


@app.command("list")
def list_containers() -> None:
    """List running containers and their image metadata."""
    try:
        containers = get_running_containers()
    except DockerConnectionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    render_containers_table(containers)


@app.command("check")
def check_updates(container: str | None = typer.Option(None, "--container", help="Check only one container by name.")) -> None:
    """Check running containers for newer image tags."""
    try:
        containers = get_running_containers()
    except DockerConnectionError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if container:
        containers = [item for item in containers if item.name == container]
        if not containers:
            typer.echo(f"Container '{container}' is not running.", err=True)
            raise typer.Exit(code=1)

    results = asyncio.run(check_all(containers))
    render_update_table(results)
    render_summary(results)


@app.command("version")
def version() -> None:
    """Print dockwatch version."""
    typer.echo(__version__)


@app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Host interface to bind web dashboard."),
    port: int = typer.Option(8080, "--port", help="Port to bind web dashboard."),
) -> None:
    """Launch NiceGUI dashboard."""
    run_web_app(host=host, port=port)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
