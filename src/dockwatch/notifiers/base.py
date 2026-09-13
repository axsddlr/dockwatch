"""Base notifier abstraction."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import UpdateResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NotificationEvent:
    """A notification that is not tied to an update check result.

    Kinds are ``"health"``, ``"prune"`` and ``"hook"``; severities are
    ``"info"``, ``"warning"`` and ``"error"``.
    """

    kind: str
    title: str
    message: str
    fields: dict[str, str]
    severity: str = "info"


def render_event_text(event: NotificationEvent) -> str:
    """Shared plain-text rendering: title, blank line, message, then fields."""
    lines = [event.title, "", event.message]
    lines.extend(f"{key}: {value}" for key, value in event.fields.items())
    return "\n".join(lines)


class BaseNotifier(ABC):
    name = "base"

    @abstractmethod
    async def send(self, results: list[UpdateResult]) -> None:
        """Send notification for update results."""

    async def send_event(self, event: NotificationEvent) -> None:
        """Send a generic notification event.

        Concrete notifiers override this with their own payload shape. The
        default renders the event as plain text and logs it, so a notifier that
        only knows about the update-result path still accepts events.
        """
        logger.info("[%s] %s", self.name, render_event_text(event))
