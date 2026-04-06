"""dockwatch package root."""

from .docker_client import DockerConnectionError, get_running_containers, parse_image_ref
from .models import ContainerInfo, RegistryType, UpdateResult
from .registry import check_all, check_container, check_dockerhub, check_ghcr

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "ContainerInfo",
    "RegistryType",
    "UpdateResult",
    "DockerConnectionError",
    "get_running_containers",
    "parse_image_ref",
    "check_container",
    "check_dockerhub",
    "check_ghcr",
    "check_all",
]
