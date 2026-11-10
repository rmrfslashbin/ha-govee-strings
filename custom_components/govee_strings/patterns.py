"""Saved per-bulb patterns, shared by every string."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import SIGNAL_PATTERNS_UPDATED, STORAGE_KEY_PATTERNS, STORAGE_VERSION
from .device import Bulb


class Fit(StrEnum):
    """How to apply a pattern to a string with a different bulb count."""

    EXACT = "exact"
    REPEAT = "repeat"
    TRUNCATE = "truncate"


class PatternMismatchError(ValueError):
    """The pattern's bulb count doesn't match the string, and fit is exact."""


def fit_bulbs(bulbs: list[Bulb], count: int, fit: Fit) -> list[Bulb]:
    """Resize a pattern to ``count`` bulbs according to ``fit``."""
    if len(bulbs) == count:
        return list(bulbs)
    if fit is Fit.EXACT:
        raise PatternMismatchError(
            f"pattern has {len(bulbs)} bulbs, the string has {count}; pass fit: repeat or truncate"
        )
    if fit is Fit.TRUNCATE and len(bulbs) < count:
        raise PatternMismatchError(
            f"pattern has {len(bulbs)} bulbs, fewer than the string's {count}; use fit: repeat"
        )
    return [bulbs[i % len(bulbs)] for i in range(count)]


class PatternStore:
    """Named patterns, persisted in .storage."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY_PATTERNS)
        self._patterns: dict[str, list[Bulb]] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._patterns = {
            name: [Bulb.from_dict(b) for b in p.get("bulbs", [])]
            for name, p in data.get("patterns", {}).items()
        }

    def names(self, bulb_count: int | None = None) -> list[str]:
        return sorted(
            n for n, b in self._patterns.items() if bulb_count is None or len(b) == bulb_count
        )

    def get(self, name: str) -> list[Bulb]:
        try:
            return self._patterns[name]
        except KeyError:
            raise KeyError(f"no saved pattern named {name!r}") from None

    def save(self, name: str, bulbs: list[Bulb]) -> None:
        if not name.strip():
            raise ValueError("pattern name must not be empty")
        if not bulbs:
            raise ValueError("a pattern needs at least one bulb")
        self._patterns[name] = [Bulb(b.rgb, b.brightness, b.on) for b in bulbs]
        self._persist()

    def delete(self, name: str) -> None:
        self.get(name)
        del self._patterns[name]
        self._persist()

    def _persist(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "patterns": {
                    n: {"bulbs": [b.as_dict() for b in bulbs]}
                    for n, bulbs in self._patterns.items()
                }
            },
            1.0,
        )
        async_dispatcher_send(self._hass, SIGNAL_PATTERNS_UPDATED)
