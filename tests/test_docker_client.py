from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from docker.errors import DockerException

import dockwatch.docker_client as docker_client_module
from dockwatch.docker_client import (
    EXEC_OUTPUT_LIMIT,
    ExecResult,
    ImageInfo,
    delete_container,
    delete_image,
    exec_in_container,
    get_local_platform,
    get_running_containers,
    in_use_image_ids,
    list_images,
    parse_image_ref,
    remove_image,
    restart_container,
)
from dockwatch.models import RegistryType


class FakeImage:
    def __init__(self) -> None:
        self.attrs = {"RepoDigests": ["example@sha256:abc123"]}
        self.tags = ["docker.io/library/nginx:1.0.0"]


class FakeContainer:
    def __init__(self, state: dict | None = None) -> None:
        self.name = "web"
        self.id = "abcdef1234567890"
        self.attrs = {
            "Config": {
                "Image": "docker.io/library/nginx:1.0.0",
                "Labels": {
                    "dockwatch.enable": "true",
                    "dockwatch.include_tags": "^1\\.;^2\\.",
                    "com.docker.compose.project": "media",
                    "com.docker.compose.service": "web",
                },
            }
        }
        if state is not None:
            self.attrs["State"] = state
        self.image = FakeImage()


class FakeDockerClient:
    def __init__(self) -> None:
        self.containers = self
        self.images = self
        self.list_kwargs: dict[str, object] | None = None
        self.removed_container: tuple[str, bool] | None = None
        self.removed_image: tuple[str, bool] | None = None
        self.close_called = False
        self.container_get_raises: Exception | None = None
        self.image_remove_raises: Exception | None = None
        self.containers_to_list: list[FakeContainer] | None = None

    def list(self, **kwargs) -> list[FakeContainer]:
        self.list_kwargs = kwargs
        if self.containers_to_list is not None:
            return self.containers_to_list
        return [FakeContainer()]

    def get(self, name: str) -> FakeContainer:
        if self.container_get_raises:
            raise self.container_get_raises
        container = FakeContainer()
        container.remove = lambda force=False: setattr(self, "removed_container", (name, force))
        return container

    def remove(self, image_id: str, force: bool = False) -> None:
        if self.image_remove_raises:
            raise self.image_remove_raises
        self.removed_image = (image_id, force)

    def close(self) -> None:
        self.close_called = True


class DockerClientTests(unittest.TestCase):
    def test_parse_image_ref_reads_label_list_overrides(self) -> None:
        info = parse_image_ref(
            "docker.io/library/nginx:1.0.0",
            labels={
                "dockwatch.include_tags": "^1\\.;^2\\.",
                "dockwatch.exclude_tags": "-rc$,-beta$",
            },
        )

        self.assertEqual(info.registry, RegistryType.DOCKERHUB)
        self.assertEqual(info.include_tags_override, [r"^1\.", r"^2\."])
        self.assertEqual(info.exclude_tags_override, [r"-rc$", r"-beta$"])

    def test_parse_image_ref_treats_single_segment_local_images_as_unknown(self) -> None:
        info = parse_image_ref("dockwatch-local:dev")

        self.assertEqual(info.registry, RegistryType.UNKNOWN)
        self.assertEqual(info.namespace, "library")
        self.assertEqual(info.image_name, "dockwatch-local")
        self.assertEqual(info.current_tag, "dev")

    def test_get_running_containers_uses_docker_metadata(self) -> None:
        fake_client = FakeDockerClient()
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client):
            containers = get_running_containers()

        self.assertEqual(len(containers), 1)
        container = containers[0]
        self.assertEqual(container.name, "web")
        self.assertEqual(container.container_id, "abcdef123456")
        self.assertEqual(container.registry, RegistryType.DOCKERHUB)
        self.assertTrue(container.watch_enabled)
        self.assertEqual(container.repo_digest, "example@sha256:abc123")
        self.assertEqual(container.compose_project, "media")
        self.assertEqual(container.compose_service, "web")
        self.assertEqual(fake_client.list_kwargs, {"all": True})

    def test_parse_image_ref_detects_codeberg_registry(self) -> None:
        info = parse_image_ref("codeberg.org/readeck/readeck:latest")

        self.assertEqual(info.registry, RegistryType.CODEBERG)
        self.assertEqual(info.namespace, "readeck")
        self.assertEqual(info.image_name, "readeck")
        self.assertEqual(info.current_tag, "latest")

    def test_get_running_containers_reads_state_and_health_status(self) -> None:
        fake_client = FakeDockerClient()
        fake_client.containers_to_list = [
            FakeContainer(state={"Status": "running", "Health": {"Status": "healthy"}})
        ]
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client):
            containers = get_running_containers()

        self.assertEqual(containers[0].state, "running")
        self.assertEqual(containers[0].health_status, "healthy")

    def test_get_running_containers_health_status_is_none_without_healthcheck(self) -> None:
        fake_client = FakeDockerClient()
        fake_client.containers_to_list = [FakeContainer(state={"Status": "running"})]
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client):
            containers = get_running_containers()

        self.assertEqual(containers[0].state, "running")
        self.assertIsNone(containers[0].health_status)

    def test_get_running_containers_state_is_none_without_state_attrs(self) -> None:
        fake_client = FakeDockerClient()
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client):
            containers = get_running_containers()

        self.assertIsNone(containers[0].state)
        self.assertIsNone(containers[0].health_status)

    def test_parse_image_ref_reads_health_restart_override_label(self) -> None:
        info = parse_image_ref(
            "docker.io/library/nginx:1.0.0",
            labels={"dockwatch.health.auto_restart": "true"},
        )

        self.assertIs(info.health_restart_override, True)

    def test_parse_image_ref_health_restart_override_defaults_to_none(self) -> None:
        info = parse_image_ref("docker.io/library/nginx:1.0.0")

        self.assertIsNone(info.health_restart_override)

    def test_parse_image_ref_carries_state_and_health_through_empty_ref_branch(self) -> None:
        info = parse_image_ref("", state="exited", health_status="unhealthy")

        self.assertEqual(info.state, "exited")
        self.assertEqual(info.health_status, "unhealthy")

    def test_parse_image_ref_carries_state_and_health_through_normal_branch(self) -> None:
        info = parse_image_ref(
            "docker.io/library/nginx:1.0.0",
            state="running",
            health_status="starting",
        )

        self.assertEqual(info.state, "running")
        self.assertEqual(info.health_status, "starting")

    def test_parse_image_ref_carries_state_and_health_through_bare_registry_branch(self) -> None:
        info = parse_image_ref("docker.io", state="created", health_status=None)

        self.assertEqual(info.image_name, "unknown")
        self.assertEqual(info.state, "created")
        self.assertIsNone(info.health_status)


class DeleteTests(unittest.TestCase):
    def test_delete_container_calls_remove_with_force(self) -> None:
        fake_client = FakeDockerClient()
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client):
            delete_container("web", force=True)

        self.assertEqual(fake_client.removed_container, ("web", True))

    def test_delete_container_defaults_force_false(self) -> None:
        fake_client = FakeDockerClient()
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client):
            delete_container("web")

        self.assertEqual(fake_client.removed_container, ("web", False))

    def test_delete_image_calls_images_remove(self) -> None:
        fake_client = FakeDockerClient()
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client):
            delete_image("sha256:abc123", force=True)

        self.assertEqual(fake_client.removed_image, ("sha256:abc123", True))

    def test_delete_container_propagates_docker_exception_on_get(self) -> None:
        from docker.errors import DockerException

        fake_client = FakeDockerClient()
        fake_client.container_get_raises = DockerException("container not found")
        with (
            patch("dockwatch.docker_client.docker.from_env", return_value=fake_client),
            self.assertRaises(DockerException) as ctx,
        ):
            delete_container("nonexistent")

        self.assertIn("container not found", str(ctx.exception))
        self.assertTrue(fake_client.close_called)

    def test_delete_container_propagates_docker_exception_on_remove(self) -> None:
        from docker.errors import DockerException

        fake_client = FakeDockerClient()
        container = FakeContainer()
        container.remove = lambda force=False: (_ for _ in ()).throw(
            DockerException("container in use")
        )
        with (
            patch("dockwatch.docker_client.docker.from_env", return_value=fake_client),
            patch.object(fake_client, "get", return_value=container),
            self.assertRaises(DockerException) as ctx,
        ):
            delete_container("web")

        self.assertIn("container in use", str(ctx.exception))
        self.assertTrue(fake_client.close_called)

    def test_delete_image_propagates_docker_exception(self) -> None:
        from docker.errors import DockerException

        fake_client = FakeDockerClient()
        fake_client.image_remove_raises = DockerException("image in use")
        with (
            patch("dockwatch.docker_client.docker.from_env", return_value=fake_client),
            self.assertRaises(DockerException) as ctx,
        ):
            delete_image("sha256:abc123")

        self.assertIn("image in use", str(ctx.exception))
        self.assertTrue(fake_client.close_called)

    def test_delete_image_defaults_force_false(self) -> None:
        fake_client = FakeDockerClient()
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client):
            delete_image("sha256:abc123")

        self.assertEqual(fake_client.removed_image, ("sha256:abc123", False))


class LocalPlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        docker_client_module.get_local_platform.cache_clear()
        self.addCleanup(docker_client_module.get_local_platform.cache_clear)

    def test_returns_linux_arch_from_daemon_version(self) -> None:
        fake_client = FakeDockerClient()
        fake_client.version = lambda: {"Arch": "arm64"}
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client):
            platform = get_local_platform()

        self.assertEqual(platform, ("linux", "arm64"))

    def test_returns_none_when_daemon_unreachable(self) -> None:
        from docker.errors import DockerException

        with patch("dockwatch.docker_client.docker.from_env", side_effect=DockerException("no daemon")):
            platform = get_local_platform()

        self.assertIsNone(platform)

    def test_result_is_cached_across_calls(self) -> None:
        fake_client = FakeDockerClient()
        fake_client.version = lambda: {"Arch": "amd64"}
        with patch("dockwatch.docker_client.docker.from_env", return_value=fake_client) as mock_from_env:
            first = get_local_platform()
            second = get_local_platform()

        self.assertEqual(first, ("linux", "amd64"))
        self.assertEqual(second, ("linux", "amd64"))
        mock_from_env.assert_called_once()


class FakeRestartContainer:
    def __init__(self) -> None:
        self.restart_calls: list[dict[str, object]] = []
        self.restart_raises: Exception | None = None

    def restart(self, **kwargs: object) -> None:
        if self.restart_raises is not None:
            raise self.restart_raises
        self.restart_calls.append(dict(kwargs))


class FakeRestartClient:
    def __init__(self) -> None:
        self.containers = self
        self.container = FakeRestartContainer()
        self.get_calls: list[str] = []
        self.get_raises: Exception | None = None
        self.close_called = False

    def get(self, name: str) -> FakeRestartContainer:
        self.get_calls.append(name)
        if self.get_raises is not None:
            raise self.get_raises
        return self.container

    def close(self) -> None:
        self.close_called = True


class FakeExecStream:
    """Model of docker's ``CancellableStream`` from ``exec_start(stream=True)``.

    Iteration yields one frame at a time like a socket read; ``close()`` marks
    the stream closed and releases the gate, so a worker thread blocked in
    ``__next__`` wakes and terminates -- mirroring how ``CancellableStream.close()``
    shuts down the socket under a blocked reader.
    """

    def __init__(
        self,
        frames: list[bytes],
        gate: threading.Event | None = None,
        error: Exception | None = None,
    ) -> None:
        self._frames = list(frames)
        self._gate = gate
        self._error = error
        self.closed = False
        # True once the stream is drained to natural EOF (no frames left), as
        # opposed to being stopped early by close(). Lets exec_inspect model the
        # daemon: an exec whose output is still being produced reports a
        # "running" (ExitCode=None) status until the stream is exhausted.
        self.exhausted = False

    def __iter__(self) -> FakeExecStream:
        return self

    def __next__(self) -> bytes:
        if self._gate is not None and not self._gate.is_set():
            # Block like an idle socket until the test (or close()) releases it.
            self._gate.wait(10)
        if self.closed:
            # close() shut the stream; the reader must stop, the way the real
            # CancellableStream turns a shutdown socket into StopIteration.
            raise StopIteration
        if self._error is not None:
            raise self._error
        if not self._frames:
            self.exhausted = True
            raise StopIteration
        return self._frames.pop(0)

    def close(self) -> None:
        self.closed = True
        if self._gate is not None:
            self._gate.set()


class FakeExecApi:
    def __init__(self) -> None:
        self.exec_create_calls: list[tuple[str, dict[str, object]]] = []
        self.exec_start_calls: list[tuple[str, dict[str, object]]] = []
        self.exec_inspect_calls: list[str] = []
        self.exec_id = "exec-1"
        self.exec_start_returns: bytes = b""
        self.exec_start_frames: list[bytes] | None = None
        self.exec_start_error: Exception | None = None
        self.exec_start_iter_error: Exception | None = None
        self.exec_start_gate: threading.Event | None = None
        self.exec_start_stream: FakeExecStream | None = None
        self.exec_create_error: Exception | None = None
        self.exit_code: int | None = 0
        # When True, exec_inspect reports ExitCode=None while the exec's output
        # stream has not yet been drained to EOF (still running), and the
        # concrete `exit_code` only once it is exhausted -- mirroring the
        # daemon, whose `ExitCode` is null while an exec is still running.
        self.exit_code_none_until_exhausted = False

    def exec_create(self, container: str, **kwargs: object) -> dict[str, str]:
        if self.exec_create_error is not None:
            raise self.exec_create_error
        self.exec_create_calls.append((container, dict(kwargs)))
        return {"Id": self.exec_id}

    def exec_start(self, exec_id: str, *, stream: bool = False) -> bytes | FakeExecStream:
        self.exec_start_calls.append((exec_id, {"stream": stream}))
        if self.exec_start_error is not None:
            raise self.exec_start_error
        frames = (
            list(self.exec_start_frames)
            if self.exec_start_frames is not None
            else ([self.exec_start_returns] if self.exec_start_returns else [])
        )
        self.exec_start_stream = FakeExecStream(
            frames, gate=self.exec_start_gate, error=self.exec_start_iter_error
        )
        if stream:
            return self.exec_start_stream
        return b"".join(frames)

    def exec_inspect(self, exec_id: str) -> dict[str, int | None]:
        self.exec_inspect_calls.append(exec_id)
        if (
            self.exit_code_none_until_exhausted
            and self.exec_start_stream is not None
            and not self.exec_start_stream.exhausted
        ):
            # The command is still running: the daemon reports ExitCode=null.
            return {"ExitCode": None}
        return {"ExitCode": self.exit_code}


class FakeExecDockerClient:
    def __init__(self, api: FakeExecApi | None = None) -> None:
        self.api = api if api is not None else FakeExecApi()
        self.close_called = False

    def close(self) -> None:
        self.close_called = True


def _exec_call(
    api: FakeExecApi,
    command: str = "echo hello",
    **kwargs: object,
) -> tuple[ExecResult, FakeExecDockerClient]:
    client = FakeExecDockerClient(api)
    with patch("dockwatch.docker_client.get_docker_client", return_value=client):
        result = exec_in_container("web", command, **kwargs)
    return result, client


class FakeImageEntry:
    def __init__(self, image_id: str | None, attrs: dict[str, object]) -> None:
        self.id = image_id
        self.attrs = attrs


class FakeImagesClient:
    def __init__(self, entries: list[FakeImageEntry] | None = None) -> None:
        self.images = self
        self.entries = entries if entries is not None else []
        self.list_calls = 0
        self.remove_calls: list[tuple[str, dict[str, object]]] = []
        self.list_raises: Exception | None = None
        self.remove_raises: Exception | None = None
        self.close_called = False

    def list(self) -> list[FakeImageEntry]:
        self.list_calls += 1
        if self.list_raises is not None:
            raise self.list_raises
        return self.entries

    def remove(self, image_id: str, **kwargs: object) -> None:
        if self.remove_raises is not None:
            raise self.remove_raises
        self.remove_calls.append((image_id, dict(kwargs)))

    def close(self) -> None:
        self.close_called = True


class RestartContainerTests(unittest.TestCase):
    def test_restart_container_passes_timeout(self) -> None:
        fake_client = FakeRestartClient()
        with patch("dockwatch.docker_client.get_docker_client", return_value=fake_client):
            restart_container("web", timeout=25)

        self.assertEqual(fake_client.get_calls, ["web"])
        self.assertEqual(fake_client.container.restart_calls, [{"timeout": 25}])

    def test_restart_container_defaults_timeout_to_ten(self) -> None:
        fake_client = FakeRestartClient()
        with patch("dockwatch.docker_client.get_docker_client", return_value=fake_client):
            restart_container("web")

        self.assertEqual(fake_client.container.restart_calls, [{"timeout": 10}])

    def test_restart_container_closes_client_when_container_is_missing(self) -> None:
        fake_client = FakeRestartClient()
        fake_client.get_raises = DockerException("no such container")
        with (
            patch("dockwatch.docker_client.get_docker_client", return_value=fake_client),
            self.assertRaises(DockerException) as ctx,
        ):
            restart_container("web")

        self.assertIn("no such container", str(ctx.exception))
        self.assertTrue(fake_client.close_called)

    def test_restart_container_propagates_restart_failure_and_closes(self) -> None:
        fake_client = FakeRestartClient()
        fake_client.container.restart_raises = DockerException("cannot restart")
        with (
            patch("dockwatch.docker_client.get_docker_client", return_value=fake_client),
            self.assertRaises(DockerException) as ctx,
        ):
            restart_container("web")

        self.assertIn("cannot restart", str(ctx.exception))
        self.assertTrue(fake_client.close_called)


class ExecInContainerTests(unittest.TestCase):
    def test_exec_output_limit_is_eight_kib(self) -> None:
        self.assertEqual(EXEC_OUTPUT_LIMIT, 8192)

    def test_exec_in_container_runs_the_command_through_sh(self) -> None:
        api = FakeExecApi()
        api.exec_start_returns = b"hello\n"

        result, _ = _exec_call(api)

        self.assertEqual(
            api.exec_create_calls,
            [("web", {"cmd": ["/bin/sh", "-lc", "echo hello"], "stdout": True, "stderr": True})],
        )
        self.assertEqual(api.exec_start_calls, [("exec-1", {"stream": True})])
        self.assertEqual(api.exec_inspect_calls, ["exec-1"])
        self.assertEqual(result, ExecResult(exit_code=0, output="hello\n", truncated=False))

    def test_exec_in_container_forwards_user_and_workdir_when_set(self) -> None:
        api = FakeExecApi()

        _exec_call(api, user="1000:1000", workdir="/srv/app")

        create_kwargs = api.exec_create_calls[0][1]
        self.assertEqual(create_kwargs["user"], "1000:1000")
        self.assertEqual(create_kwargs["workdir"], "/srv/app")

    def test_exec_in_container_omits_blank_user_and_workdir(self) -> None:
        api = FakeExecApi()

        _exec_call(api, user=None, workdir=None)
        _exec_call(api, user="", workdir="")

        for _, create_kwargs in api.exec_create_calls:
            self.assertNotIn("user", create_kwargs)
            self.assertNotIn("workdir", create_kwargs)

    def test_exec_in_container_returns_the_exit_code(self) -> None:
        api = FakeExecApi()
        api.exit_code = 7

        result, _ = _exec_call(api)

        self.assertEqual(result.exit_code, 7)

    def test_exec_in_container_treats_none_exit_code_as_minus_one(self) -> None:
        api = FakeExecApi()
        api.exit_code = None

        result, _ = _exec_call(api)

        self.assertEqual(result.exit_code, -1)

    def test_exec_in_container_decodes_output_with_replacement(self) -> None:
        api = FakeExecApi()
        api.exec_start_returns = b"ok\xff"

        result, _ = _exec_call(api)

        self.assertEqual(result.output, "ok\ufffd")

    def test_exec_in_container_truncates_output_over_eight_kib(self) -> None:
        api = FakeExecApi()
        api.exec_start_returns = b"a" * (EXEC_OUTPUT_LIMIT + 1)

        result, _ = _exec_call(api)

        self.assertTrue(result.truncated)
        self.assertEqual(len(result.output), EXEC_OUTPUT_LIMIT)
        self.assertEqual(result.output, "a" * EXEC_OUTPUT_LIMIT)

    def test_exec_in_container_keeps_output_at_the_limit(self) -> None:
        api = FakeExecApi()
        api.exec_start_returns = b"a" * EXEC_OUTPUT_LIMIT

        result, _ = _exec_call(api)

        self.assertFalse(result.truncated)
        self.assertEqual(result.output, "a" * EXEC_OUTPUT_LIMIT)

    def test_exec_in_container_counts_the_limit_in_bytes_not_characters(self) -> None:
        api = FakeExecApi()
        # 5000 characters but 10000 UTF-8 bytes: under the code-point reading of
        # the 8 KiB cap, over its byte reading.
        api.exec_start_returns = "é".encode() * 5000

        result, _ = _exec_call(api)

        self.assertTrue(result.truncated)
        self.assertEqual(len(result.output.encode("utf-8")), EXEC_OUTPUT_LIMIT)

    def test_exec_in_container_preserves_real_exit_code_when_output_is_truncated(self) -> None:
        api = FakeExecApi()
        api.exit_code_none_until_exhausted = True
        api.exit_code = 0
        # Output exceeds the cap across several frames: the worker must drain
        # and discard the surplus to EOF so exec_inspect sees the command has
        # finished and reports its real exit code (0) rather than -1.
        api.exec_start_frames = [b"a" * EXEC_OUTPUT_LIMIT, b"b" * 256, b"c" * 256]

        result, _ = _exec_call(api)

        self.assertEqual(result.exit_code, 0)
        self.assertTrue(result.truncated)
        self.assertEqual(len(result.output), EXEC_OUTPUT_LIMIT)

    def test_exec_in_container_gives_up_when_the_command_outlives_its_timeout(self) -> None:
        api = FakeExecApi()
        gate = threading.Event()
        api.exec_start_gate = gate
        self.addCleanup(gate.set)
        client = FakeExecDockerClient(api)

        with (
            patch("dockwatch.docker_client.get_docker_client", return_value=client),
            self.assertRaises(DockerException) as ctx,
        ):
            exec_in_container("web", "sleep 999", timeout_seconds=1)

        self.assertIn("timed out", str(ctx.exception))
        self.assertIn("1s", str(ctx.exception))
        self.assertTrue(client.close_called)
        # The stream was closed on timeout, which releases the gate the worker
        # is blocked on -- the worker is reclaimed instead of leaked.
        stream = api.exec_start_stream
        self.assertIsNotNone(stream)
        self.assertTrue(stream.closed)
        self.assertTrue(gate.is_set())

    def test_exec_in_container_propagates_exec_start_failure_and_closes(self) -> None:
        api = FakeExecApi()
        api.exec_start_error = DockerException("exec failed")
        client = FakeExecDockerClient(api)

        with (
            patch("dockwatch.docker_client.get_docker_client", return_value=client),
            self.assertRaises(DockerException) as ctx,
        ):
            exec_in_container("web", "echo hi")

        self.assertIn("exec failed", str(ctx.exception))
        self.assertTrue(client.close_called)

    def test_exec_in_container_propagates_a_worker_read_error_and_closes(self) -> None:
        import sys
        import traceback

        api = FakeExecApi()
        api.exec_start_iter_error = DockerException("frame read failed")
        client = FakeExecDockerClient(api)

        raised = None
        formatted = ""
        with patch("dockwatch.docker_client.get_docker_client", return_value=client):
            try:
                exec_in_container("web", "echo hi")
            except DockerException:
                raised = sys.exc_info()[1]
                formatted = "".join(traceback.format_exception(*sys.exc_info()))

        self.assertIsNotNone(raised)
        self.assertIn("frame read failed", str(raised))
        self.assertTrue(client.close_called)
        # The worker's original traceback survives the cross-thread re-raise,
        # rather than being flattened into the caller's frame.
        self.assertIn("_run", formatted)

    def test_exec_in_container_closes_client_when_exec_create_fails(self) -> None:
        api = FakeExecApi()
        api.exec_create_error = DockerException("no such container")
        client = FakeExecDockerClient(api)

        with (
            patch("dockwatch.docker_client.get_docker_client", return_value=client),
            self.assertRaises(DockerException) as ctx,
        ):
            exec_in_container("web", "echo hi")

        self.assertIn("no such container", str(ctx.exception))
        self.assertTrue(client.close_called)
        self.assertEqual(api.exec_start_calls, [])


class ListImagesTests(unittest.TestCase):
    def test_list_images_reads_id_tags_created_and_size(self) -> None:
        fake_client = FakeImagesClient(
            [
                FakeImageEntry(
                    "sha256:aaa",
                    {"RepoTags": ["nginx:1.0"], "Created": 1700000000, "Size": 12345},
                )
            ]
        )
        with patch("dockwatch.docker_client.get_docker_client", return_value=fake_client):
            images = list_images()

        self.assertEqual(images, [ImageInfo("sha256:aaa", ["nginx:1.0"], 1700000000, 12345)])

    def test_list_images_defaults_dangling_repo_tags_to_empty(self) -> None:
        fake_client = FakeImagesClient(
            [FakeImageEntry("sha256:bbb", {"RepoTags": None, "Created": 1, "Size": 0})]
        )
        with patch("dockwatch.docker_client.get_docker_client", return_value=fake_client):
            images = list_images()

        self.assertEqual(images[0].repo_tags, [])

    def test_list_images_defaults_missing_and_non_numeric_attrs(self) -> None:
        fake_client = FakeImagesClient(
            [
                FakeImageEntry("sha256:ccc", {}),
                FakeImageEntry("sha256:ddd", {"Created": "not-a-number", "Size": None}),
            ]
        )
        with patch("dockwatch.docker_client.get_docker_client", return_value=fake_client):
            images = list_images()

        self.assertEqual((images[0].created, images[0].size_bytes), (0, 0))
        self.assertEqual((images[1].created, images[1].size_bytes), (0, 0))

    def test_list_images_skips_images_without_an_id(self) -> None:
        fake_client = FakeImagesClient(
            [
                FakeImageEntry(None, {"RepoTags": ["dangling:latest"]}),
                FakeImageEntry("", {"RepoTags": ["blank:latest"]}),
                FakeImageEntry("sha256:eee", {"RepoTags": ["keep:latest"]}),
            ]
        )
        with patch("dockwatch.docker_client.get_docker_client", return_value=fake_client):
            images = list_images()

        self.assertEqual([image.image_id for image in images], ["sha256:eee"])

    def test_list_images_propagates_docker_exception_and_closes(self) -> None:
        fake_client = FakeImagesClient()
        fake_client.list_raises = DockerException("daemon unavailable")
        with (
            patch("dockwatch.docker_client.get_docker_client", return_value=fake_client),
            self.assertRaises(DockerException) as ctx,
        ):
            list_images()

        self.assertIn("daemon unavailable", str(ctx.exception))
        self.assertTrue(fake_client.close_called)


class FakeInUseImage:
    def __init__(self, image_id: str | None) -> None:
        self.id = image_id


class FakeInUseContainer:
    def __init__(self, image: FakeInUseImage | None) -> None:
        self.image = image


class FakeInUseClient:
    def __init__(self, containers: list[FakeInUseContainer]) -> None:
        self.containers = self
        self._containers = containers
        self.list_kwargs: dict[str, object] | None = None
        self.close_called = False

    def list(self, **kwargs: object) -> list[FakeInUseContainer]:
        self.list_kwargs = kwargs
        return self._containers

    def close(self) -> None:
        self.close_called = True


class InUseImageIdsTests(unittest.TestCase):
    def test_returns_image_id_of_every_container(self) -> None:
        fake_client = FakeInUseClient(
            [
                FakeInUseContainer(FakeInUseImage("sha256:aaa")),
                FakeInUseContainer(FakeInUseImage("sha256:bbb")),
            ]
        )
        with patch("dockwatch.docker_client.get_docker_client", return_value=fake_client):
            ids = in_use_image_ids()

        self.assertEqual(ids, {"sha256:aaa", "sha256:bbb"})
        self.assertEqual(fake_client.list_kwargs, {"all": True})
        self.assertTrue(fake_client.close_called)

    def test_skips_containers_without_an_image(self) -> None:
        fake_client = FakeInUseClient(
            [
                FakeInUseContainer(None),
                FakeInUseContainer(FakeInUseImage("sha256:aaa")),
                FakeInUseContainer(FakeInUseImage(None)),
            ]
        )
        with patch("dockwatch.docker_client.get_docker_client", return_value=fake_client):
            ids = in_use_image_ids()

        self.assertEqual(ids, {"sha256:aaa"})


class RemoveImageTests(unittest.TestCase):
    def test_remove_image_never_forces(self) -> None:
        fake_client = FakeImagesClient()
        with patch("dockwatch.docker_client.get_docker_client", return_value=fake_client):
            remove_image("sha256:abc123")

        self.assertEqual(fake_client.remove_calls, [("sha256:abc123", {})])

    def test_remove_image_propagates_docker_exception_and_closes(self) -> None:
        fake_client = FakeImagesClient()
        fake_client.remove_raises = DockerException("image is in use")
        with (
            patch("dockwatch.docker_client.get_docker_client", return_value=fake_client),
            self.assertRaises(DockerException) as ctx,
        ):
            remove_image("sha256:abc123")

        self.assertIn("image is in use", str(ctx.exception))
        self.assertTrue(fake_client.close_called)


if __name__ == "__main__":
    unittest.main()
