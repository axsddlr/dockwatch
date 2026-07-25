"""Typer CLI entrypoint for dockwatch."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from enum import Enum

import typer
from packaging.version import Version

from . import __version__
from .config import CONFIG_PATH, DockwatchConfig, load_config, migrate_pinned_ignored_to_db
from .db import ManifestStore
from .display import render_containers_table, render_scan_results, render_summary, render_update_table
from .docker_client import get_image_id, get_running_containers
from .models import ContainerInfo, RegistryType, TrivyScanResult, UpdateResult
from .notifiers import build_notifiers, filter_notification_results, send_configured_notifications
from .registry import check_all
from .scheduler import ScheduledCheckRunner
from .sources import discover_containers, discover_environments
from .trivy import TrivyNotFoundError, scan_image
from .updater import build_update_plan, describe_update_plan, execute_update


app = typer.Typer(
    help=(
        "Monitor running Docker containers for available image updates.\n\n"
        "Examples:\n"
        "  dockwatch list\n"
        "  dockwatch check\n"
        "  dockwatch check --container nginx\n"
        "  dockwatch update nginx --dry-run\n"
        "  dockwatch version"
    )
)
config_app = typer.Typer(help="Manage dockwatch configuration.")
notify_app = typer.Typer(help="Manage notifications.")
app.add_typer(config_app, name="config")
app.add_typer(notify_app, name="notify")


@app.callback()
def main_callback() -> None:
    """Run one-time setup that every CLI invocation depends on.

    Ensures any legacy TOML `pinned`/`ignored` values are imported into the
    SQLite-backed store before a subcommand can read or write flags. The
    migration itself is idempotent (it only imports into an empty store),
    so calling it on every CLI startup is safe and cheap.
    """
    migrate_pinned_ignored_to_db(CONFIG_PATH, ManifestStore())


@app.command("list")
def list_containers(
    source: str = typer.Option("local", "--source", help="Container source: local, portainer, or all."),
    environment: str | None = typer.Option(None, "--environment", help="Portainer environment ID."),
) -> None:
    """List running containers and their image metadata."""
    config = load_config()
    discovery = asyncio.run(discover_containers(config, source=source, selected_environment=environment))
    containers = discovery.containers
    for error in discovery.errors:
        typer.echo(error, err=True)
    if source == "portainer" and discovery.errors and not containers:
        raise typer.Exit(code=1)

    render_containers_table(containers)


@app.command("check")
def check_updates(
    container: str | None = typer.Option(None, "--container", help="Check only one container by name."),
    notify: bool = typer.Option(False, "--notify", help="Send configured notifications after checking."),
    json_output: bool = typer.Option(False, "--json", help="Print check output as JSON."),
    outdated_only: bool = typer.Option(False, "--outdated-only", help="Show only outdated containers."),
    major_only: bool = typer.Option(False, "--major-only", help="Show only outdated containers with MAJOR semver bumps."),
    source: str = typer.Option("local", "--source", help="Container source: local, portainer, or all."),
    environment: str | None = typer.Option(None, "--environment", help="Portainer environment ID."),
) -> None:
    """Check running containers for newer image tags."""
    config = load_config()
    discovery = asyncio.run(discover_containers(config, source=source, selected_environment=environment))
    containers = discovery.containers
    for error in discovery.errors:
        typer.echo(error, err=True)
    if source == "portainer" and discovery.errors and not containers:
        raise typer.Exit(code=1)

    if container:
        containers = [item for item in containers if item.name == container]
        if not containers:
            typer.echo(f"Container '{container}' is not running.", err=True)
            raise typer.Exit(code=1)

    store = ManifestStore()
    results = asyncio.run(check_all(containers, config, store=store, max_concurrency=config.max_concurrent_checks))
    if outdated_only:
        results = [result for result in results if result.is_outdated is True]
    if major_only:
        results = [
            result
            for result in results
            if result.is_outdated is True
            and result.version_diff is not None
            and result.version_diff.bump_type == "MAJOR"
        ]

    if json_output:
        def _serialize(value):  # noqa: ANN001
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, Version):
                return str(value)
            return value

        payload = [asdict(result, dict_factory=dict) for result in results]
        typer.echo(json.dumps(payload, default=_serialize, indent=2))
    else:
        render_update_table(results)
        render_summary(results)
    if notify:
        notifiers = build_notifiers(config)
        if not notifiers:
            typer.echo("No notifiers configured. Set webhook_url, discord_webhook, or ntfy_url in config.", err=True)
            raise typer.Exit(code=1)
        filtered = filter_notification_results(results, config)
        if not filtered:
            typer.echo("No notifications matched configured filters.")
            return
        errors = asyncio.run(send_configured_notifications(results, config))
        if errors:
            for error in errors:
                typer.echo(f"Notifier error: {error}", err=True)
        else:
            typer.echo("Notifications sent.")


@app.command("scan")
def scan_images(
    container: str | None = typer.Option(None, "--container", help="Scan only one container by name."),
    json_output: bool = typer.Option(False, "--json", help="Print scan output as JSON."),
    source: str = typer.Option("local", "--source", help="Container source: local, portainer, or all."),
    environment: str | None = typer.Option(None, "--environment", help="Portainer environment ID."),
) -> None:
    """Scan running container images for vulnerabilities with Trivy."""
    config = load_config()
    if not config.trivy.enabled:
        typer.echo("Trivy scanning is not enabled. Set trivy.enabled = true in config.", err=True)
        raise typer.Exit(code=1)

    try:
        discovery = asyncio.run(discover_containers(config, source=source, selected_environment=environment))
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Container discovery failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    containers = discovery.containers
    for error in discovery.errors:
        typer.echo(error, err=True)
    if source == "portainer" and discovery.errors and not containers:
        raise typer.Exit(code=1)

    if container:
        containers = [item for item in containers if item.name == container]
        if not containers:
            typer.echo(f"Container '{container}' is not running.", err=True)
            raise typer.Exit(code=1)

    store = ManifestStore()
    scan_results: list[TrivyScanResult] = []

    async def _run_scans() -> None:
        semaphore = asyncio.Semaphore(config.max_concurrent_checks)
        tasks = []
        for info in containers:
            tasks.append(_scan_container(info, config, store, semaphore))
        gathered = await asyncio.gather(*tasks)
        scan_results.extend([r for r in gathered if r is not None])

    async def _scan_container(
        info: ContainerInfo,
        cfg: DockwatchConfig,
        db_store: ManifestStore,
        sem: asyncio.Semaphore,
    ) -> TrivyScanResult | None:
        async with sem:
            image_id = get_image_id(info.name)
            if image_id:
                cached = db_store.trivy_cache_get(image_id, cache_ttl_minutes=cfg.trivy.cache_ttl_minutes)
                if cached is not None:
                    return cached
            try:
                result = await scan_image(info.image_ref, cfg.trivy)
            except TrivyNotFoundError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=1) from exc
            if image_id and not result.error:
                db_store.trivy_cache_put(image_id, result)
            return result

    try:
        asyncio.run(_run_scans())
    except typer.Exit:
        raise
    except TrivyNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if json_output:
        payload = [{
            "image_ref": r.image_ref,
            "critical": r.critical_count,
            "high": r.high_count,
            "medium": r.medium_count,
            "low": r.low_count,
            "total": r.total_count,
            "error": r.error,
            "findings": [
                {
                    "vulnerability_id": f.vulnerability_id,
                    "package": f.pkg_name,
                    "installed": f.installed_version,
                    "fixed": f.fixed_version,
                    "severity": f.severity,
                    "title": f.title,
                    "url": f.primary_url,
                }
                for f in r.findings
            ],
        } for r in scan_results]
        typer.echo(json.dumps(payload, indent=2))
    else:
        render_scan_results(scan_results)


@app.command("environments")
def list_environments() -> None:
    """List Portainer environments available to the configured API key."""
    config = load_config()
    try:
        environments = asyncio.run(discover_environments(config))
    except Exception as exc:  # noqa: BLE001
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if not environments:
        typer.echo("No Portainer environments available.")
        return

    for environment in environments:
        typer.echo(f"{environment.id}: {environment.name}")


@app.command("update")
def update_container(
    container: str,
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation and execute immediately."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the update plan without executing."),
    source: str = typer.Option("local", "--source", help="Update source. Only local is supported in this phase."),
) -> None:
    """Update one container using dockwatch's safe local workflow."""
    if source != "local":
        typer.echo("Only local Docker updates are supported in this phase.", err=True)
        raise typer.Exit(code=1)

    config = load_config()
    discovery = asyncio.run(discover_containers(config, source="local"))
    containers = [item for item in discovery.containers if item.name == container]
    if not containers:
        typer.echo(f"Container '{container}' was not found in local Docker discovery.", err=True)
        raise typer.Exit(code=1)

    store = ManifestStore()
    results = asyncio.run(check_all(containers, config, store=store, max_concurrency=1))
    if not results:
        typer.echo(f"Container '{container}' is currently ignored or unavailable.", err=True)
        raise typer.Exit(code=1)

    plan = build_update_plan(results[0], config)
    for line in describe_update_plan(plan):
        typer.echo(line)
    if not plan.allowed:
        raise typer.Exit(code=1)
    if dry_run:
        typer.echo("Dry run complete.")
        return
    if not yes and not typer.confirm(f"Proceed with updating '{container}'?"):
        typer.echo("Update cancelled.")
        raise typer.Exit(code=1)

    execution = execute_update(plan, config)
    typer.echo(execution.message)
    for line in execution.details:
        if line:
            typer.echo(f"  - {line}")
    if execution.rollback_message:
        typer.echo(f"Rollback: {execution.rollback_message}")
    if not execution.success:
        raise typer.Exit(code=1)

    refreshed = [item for item in get_running_containers() if item.name == container]
    refreshed_results = asyncio.run(check_all(refreshed, config, store=store, max_concurrency=1)) if refreshed else []
    if refreshed_results:
        render_update_table(refreshed_results)
        render_summary(refreshed_results)


@app.command("version")
def version() -> None:
    """Print dockwatch version."""
    typer.echo(__version__)


@app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", "--host", help="Host interface to bind web dashboard."),
    port: int = typer.Option(8080, "--port", help="Port to bind web dashboard."),
) -> None:
    """Launch web dashboard."""
    import uvicorn
    from .api.app import create_app
    uvicorn.run(create_app(), host=host, port=port)


@app.command("daemon")
def daemon(
    notify: bool = typer.Option(True, "--notify/--no-notify", help="Send configured notifications after each run."),
) -> None:
    """Run dockwatch in scheduled background mode using config file schedule settings."""
    config = load_config()
    store = ManifestStore()
    runner = ScheduledCheckRunner(
        config=config,
        store=store,
        notify=notify,
        emit=typer.echo,
    )
    typer.echo(
        "Starting daemon "
        f"(interval={config.schedule_interval_seconds}s, "
        f"jitter={config.schedule_jitter_seconds}s, "
        f"run_on_startup={config.run_on_startup}, "
        f"workers={config.max_concurrent_checks})."
    )
    try:
        asyncio.run(runner.serve_forever())
    except KeyboardInterrupt:
        typer.echo("Daemon stopped.")


@app.command("pin")
def pin_container(container: str) -> None:
    """Pin a container so update checks mark it as PINNED."""
    store = ManifestStore()
    store.add_flag(container, "pinned")
    typer.echo(f"Pinned: {container}")


@app.command("ignore")
def ignore_container(container: str) -> None:
    """Ignore a container in update checks."""
    store = ManifestStore()
    store.add_flag(container, "ignored")
    typer.echo(f"Ignored: {container}")


@app.command("unpin")
def unpin_container(container: str) -> None:
    """Remove a container from the pinned list."""
    store = ManifestStore()
    removed = store.remove_flag(container, "pinned")
    if not removed:
        typer.echo(f"'{container}' is not pinned.", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Unpinned: {container}")


@app.command("unignore")
def unignore_container(container: str) -> None:
    """Remove a container from the ignored list."""
    store = ManifestStore()
    removed = store.remove_flag(container, "ignored")
    if not removed:
        typer.echo(f"'{container}' is not ignored.", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Unignored: {container}")


@config_app.command("list")
def list_config() -> None:
    """Show pinned and ignored containers from config."""
    config: DockwatchConfig = load_config()
    store = ManifestStore()
    typer.echo("Pinned:")
    pinned = store.get_pinned()
    if pinned:
        for item in pinned:
            typer.echo(f"  - {item}")
    else:
        typer.echo("  (none)")

    typer.echo("Ignored:")
    ignored = store.get_ignored()
    if ignored:
        for item in ignored:
            typer.echo(f"  - {item}")
    else:
        typer.echo("  (none)")

    typer.echo("Notifications:")
    typer.echo(f"  include_tags: {', '.join(config.include_tags) if config.include_tags else '(none)'}")
    typer.echo(f"  exclude_tags: {', '.join(config.exclude_tags) if config.exclude_tags else '(none)'}")
    typer.echo(f"  webhook_url: {'(set)' if config.webhook_url else '(not set)'}")
    typer.echo(f"  discord_webhook: {'(set)' if config.discord_webhook else '(not set)'}")
    typer.echo(f"  ntfy_url: {'(set)' if config.ntfy_url else '(not set)'}")
    typer.echo(f"  notify_on: {', '.join(config.notify_on) if config.notify_on else '(none)'}")
    typer.echo(f"  first_check_notify: {config.first_check_notify}")
    typer.echo(f"  schedule_interval_seconds: {config.schedule_interval_seconds}")
    typer.echo(f"  schedule_jitter_seconds: {config.schedule_jitter_seconds}")
    typer.echo(f"  run_on_startup: {config.run_on_startup}")
    typer.echo(f"  max_concurrent_checks: {config.max_concurrent_checks}")
    typer.echo("Portainer:")
    typer.echo(f"  enabled: {config.portainer.enabled}")
    typer.echo(f"  url: {config.portainer.url or '(not set)'}")
    typer.echo(f"  api_key: {'(set)' if config.portainer.api_key else '(not set)'}")
    typer.echo(
        "  environments: "
        + (", ".join(config.portainer.environments) if config.portainer.environments else "(all)")
    )
    typer.echo("Compose projects:")
    if config.compose_projects:
        for name, project in config.compose_projects.items():
            typer.echo(f"  {name}:")
            typer.echo(f"    workdir: {project.workdir or '(not set)'}")
            typer.echo(f"    files: {', '.join(project.files) if project.files else '(default)'}")
            typer.echo(f"    project_name: {project.project_name or '(auto)'}")
    else:
        typer.echo("  (none)")


@notify_app.command("test")
def notify_test() -> None:
    """Send a test notification to all configured notifiers."""
    config = load_config()
    notifiers = build_notifiers(config)
    if not notifiers:
        typer.echo("No notifiers configured. Set webhook_url, discord_webhook, or ntfy_url in config.", err=True)
        raise typer.Exit(code=1)

    test_result = UpdateResult(
        container_info=ContainerInfo(
            name="dockwatch-test",
            container_id="test",
            image_ref="ghcr.io/example/app:1.0.0",
            registry=RegistryType.GHCR,
            namespace="example",
            image_name="app",
            current_tag="1.0.0",
        ),
        latest_tag="1.1.0",
        is_outdated=True,
        status=None,
        event="update",
        deployed_tag="1.0.0",
        remote_tag="1.1.0",
        comparison_basis="version",
        comparison_reason="remote version 1.1.0 is newer than deployed 1.0.0",
    )

    errors = asyncio.run(send_configured_notifications([test_result], config, apply_filters=False))
    if errors:
        for error in errors:
            typer.echo(f"Notifier error: {error}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Test notification sent to {len(notifiers)} notifier(s).")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
