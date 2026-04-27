from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterable

from ..models import Event


class Collector(ABC):
    """Abstract data source. Implementations yield Event objects for a time window."""

    name: str = "base"

    @abstractmethod
    def collect(self, since: datetime | None, until: datetime | None) -> Iterable[Event]:
        """Yield events with ts_start in [since, until]. Both bounds are UTC and optional."""
        raise NotImplementedError
