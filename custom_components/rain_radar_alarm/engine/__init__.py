"""Radar nowcasting engine: plain Python + numpy, no Home Assistant imports.

Everything here is blocking and CPU-bound; the integration runs it in the executor.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Forecast tuning. Defaults suit Australian convective and frontal rain."""

    horizon_min: int = 120          # furthest lead time returned
    step_min: int = 5               # timeline resolution
    rain_threshold: float = 0.2     # mm/h counted as rain
    alert_probability: float = 0.5  # rain "expected" at or above this
    clear_probability: float = 0.3  # rain "cleared" below this
    radius_base_km: float = 1.0     # uncertainty circle at lead 0 ...
    radius_growth_km: float = 0.12  # ... widening by this per minute of lead
    max_speed_kmh: float = 130.0    # storm speeds above this are treated as noise
    frames_for_motion: int = 4
    history_frames: int = 7
