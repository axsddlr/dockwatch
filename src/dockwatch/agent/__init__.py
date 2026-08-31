"""Dockwatch agent: a standalone service exposing another host's Docker
daemon to a central dockwatch instance."""

from .server import create_agent_app

__all__ = ["create_agent_app"]
