"""Radar map camera per location: recent radar, then forecast frames, as a loop.

Still image: an animated GIF (dashboards, phone notification attachments).
Live view: the same frames streamed one at a time (more-info dialog, iOS live notifications).
Drawn in memory only when someone looks at it, and reused until BoM publishes a new frame.
"""
from __future__ import annotations

from aiohttp import web

from homeassistant.components.camera import Camera, async_get_still_stream
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RainRadarConfigEntry
from .engine.render import FRAME_MS
from .entity import RainRadarEntity


async def async_setup_entry(hass: HomeAssistant, entry: RainRadarConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(RadarMapCamera(coord) for coord in entry.runtime_data.coordinators.values())


class RadarMapCamera(RainRadarEntity, Camera):
    _attr_frame_interval = FRAME_MS / 1000

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "radar_map")
        Camera.__init__(self)
        self.content_type = "image/gif"

    @property
    def available(self) -> bool:
        return super().available and (self.data.get("source") or {}).get("type") == "radar"

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        loop = await self.coordinator.async_radar_loop()
        return loop.gif if loop else None

    async def handle_async_mjpeg_stream(self, request: web.Request) -> web.StreamResponse | None:
        """Stream the loop frame by frame, holding the latest and last forecast frames."""
        step = 0
        sequence: list[bytes] = []

        async def next_frame() -> bytes | None:
            nonlocal step, sequence
            if step >= len(sequence):  # start of each pass: pick up any new radar frame
                loop = await self.coordinator.async_radar_loop()
                if loop is None:
                    return None
                sequence = [jpeg for jpeg, ms in zip(loop.jpegs, loop.durations_ms)
                            for _ in range(max(1, round(ms / FRAME_MS)))]
                step = 0
            frame = sequence[step]
            step += 1
            return frame

        return await async_get_still_stream(request, next_frame, "image/jpeg", self.frame_interval)
