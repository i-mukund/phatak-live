"""Learned corrections consumed by the prediction engine.

Defined here (not in the learning package) so the engine has no dependency on
the learning engine — data flows one way: learning writes, prediction reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain import TrainClass

DEFAULT_KEY = "default"


@dataclass(frozen=True, slots=True)
class Calibration:
    """Signed offsets in seconds. Positive means "happens later than we said"."""

    pass_offset_seconds: float = 0.0
    close_offset_seconds: float = 0.0
    open_offset_seconds: float = 0.0
    pass_mae_seconds: float = 0.0
    sample_count: int = 0

    @property
    def is_mature(self) -> bool:
        return self.sample_count >= 10


@dataclass(frozen=True, slots=True)
class CalibrationSet:
    """Per-train-class calibrations with a default fallback."""

    by_class: dict[str, Calibration] = field(default_factory=dict)

    def for_class(self, train_class: TrainClass | str) -> Calibration:
        key = train_class.value if isinstance(train_class, TrainClass) else str(train_class)
        specific = self.by_class.get(key)
        if specific is not None and specific.sample_count > 0:
            return specific
        return self.by_class.get(DEFAULT_KEY, Calibration())

    @classmethod
    def empty(cls) -> CalibrationSet:
        return cls(by_class={})
