"""dockwatch package root."""

from .config import DockwatchConfig, load_config, save_config
from .docker_client import DockerConnectionError, get_running_containers, parse_image_ref
from .models import ContainerInfo, RegistryType, UpdateResult
from .registry import check_all, check_container, check_dockerhub, check_ghcr

__version__ = "0.3.1"

__all__ = [
    "__version__",
    "ContainerInfo",
    "RegistryType",
    "UpdateResult",
    "DockwatchConfig",
    "load_config",
    "save_config",
    "DockerConnectionError",
    "get_running_containers",
    "parse_image_ref",
    "check_container",
    "check_dockerhub",
    "check_ghcr",
    "check_all",
]
