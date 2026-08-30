"""Base notifier abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import UpdateResult


class BaseNotifier(ABC):
    name = "base"

    @abstractmethod
    async def send(self, results: list[UpdateResult]) -> None:
        """Send notification for update results."""