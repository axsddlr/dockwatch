"""dockwatch package root."""

from .config import DockwatchConfig, load_config, save_config
from .docker_client import (
    DockerConnectionError,
    get_running_containers,
    parse_image_ref,
)
from .models import ContainerInfo, RegistryType, UpdateResult
from .registry import check_all, check_container, check_dockerhub, check_ghcr

__version__ = "0.13.0"

__all__ = [
    "ContainerInfo",
    "DockerConnectionError",
    "DockwatchConfig",
    "RegistryType",
    "UpdateResult",
    "__version__",
    "check_all",
    "check_container",
    "check_dockerhub",
    "check_ghcr",
    "get_running_containers",
    "load_config",
    "parse_image_ref",
    "save_config",
]
