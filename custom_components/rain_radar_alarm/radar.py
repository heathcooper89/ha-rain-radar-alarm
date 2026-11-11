"""Radar manager: one per Home Assistant instance, shared by every tracked location.

Downloads BoM frames only for radars a location currently needs, at most once per new frame,
keeps them in memory, and works out storm motion once per radar. Locations then compute their
own forecast from the shared product in a couple of milliseconds.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
import datetime as dt
import logging
from time import monotonic
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN, FALLBACK_CACHE, FALLBACK_CELL_DEG, ISSUE_AFTER_FAILURES, RADAR_IDLE_AFTER,
    RADAR_MIN_RETRY, RADAR_POLL, RADAR_STALE_AFTER, SITES_REFRESH,
)
from .engine import Settings, bom, openmeteo, sites
from .engine.product import build_product

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1


class RadarManager:
    """Owns radar data for one config entry."""

    def __init__(self, hass: HomeAssistant, settings: Settings, range_code: str) -> None:
        self.hass = hass
        self.settings = settings
        self.range_code = range_code
        self.range_km = bom.RANGE_KM[range_code]
        self.registry: list[dict] = []
        self.registry_updated: dt.datetime | None = None
        self.products: dict[int, dict] = {}
        self._raw_latest: dict[int, bytes] = {}       # newest PNG per radar, for diagnostics only
        self._needed: dict[int, float] = {}           # radar id -> monotonic time last needed
        self._last_try: dict[int, float] = {}
        self._failures = 0
        self._retry_after = 0.0                       # monotonic; backoff while BoM is unreachable
        self.last_error: str | None = None
        self.last_poll: dt.datetime | None = None
        self._lock = asyncio.Lock()
        self._listeners: list[Callable[[], None]] = []
        self._unsub: CALLBACK_TYPE | None = None
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.radar_sites")
        self._fallback: dict[tuple, tuple[float, dict]] = {}
        self._fallback_locks: dict[tuple, asyncio.Lock] = {}

    # ------------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        """Load the saved radar list and start polling. No network here."""
        stored = await self._store.async_load()
        if stored:
            self.registry = stored.get("sites", [])
            self.registry_updated = dt_util.parse_datetime(stored.get("updated", ""))
        self._unsub = async_track_time_interval(
            self.hass, self._async_poll, RADAR_POLL, cancel_on_shutdown=True)

    async def async_ensure_sites(self) -> None:
        """Read BoM's radar list if there is none saved, or it's over a week old."""
        if not self.registry or self.registry_updated is None or (
            dt_util.utcnow() - self.registry_updated > SITES_REFRESH
        ):
            await self.async_refresh_sites()

    @callback
    def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def async_remove_stored(self) -> None:
        await self._store.async_remove()

    async def async_refresh_sites(self) -> None:
        """Re-read BoM's radar locations table; keep the old list if that fails."""
        try:
            raw = await self.hass.async_add_executor_job(bom.fetch_sites_table)
            parsed = await self.hass.async_add_executor_job(sites.parse_sites, raw)
        except Exception as err:  # noqa: BLE001 - network or format problem, keep going
            _LOGGER.warning("Could not read BoM radar locations: %s", err)
            self.last_error = f"radar locations: {err}"
            return
        if parsed:
            self.registry = parsed
            self.registry_updated = dt_util.utcnow()
            await self._store.async_save({"sites": parsed, "updated": self.registry_updated.isoformat()})
            _LOGGER.debug("Loaded %d BoM radar sites", len(parsed))

    # ------------------------------------------------------------------ listeners
    @callback
    def async_add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(update)

        @callback
        def remove() -> None:
            self._listeners.remove(update)

        return remove

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    # ------------------------------------------------------------------ radar data
    def radars_for(self, lat: float, lon: float) -> list[dict]:
        return sites.candidates(self.registry, lat, lon, self.range_km)

    def is_fresh(self, product: dict | None) -> bool:
        return bool(product) and dt_util.utcnow() - product["times"][-1] <= RADAR_STALE_AFTER

    async def async_product(self, radar_id: int) -> dict | None:
        """The radar's product, fetching it first if it's missing or stale."""
        self._needed[radar_id] = monotonic()
        product = self.products.get(radar_id)
        if self.is_fresh(product):
            return product
        # No "last try" means never tried. (The monotonic clock starts near zero at boot, so a
        # default of 0 would block the first download for a couple of minutes after a reboot.)
        last = self._last_try.get(radar_id)
        if last is None or monotonic() - last >= RADAR_MIN_RETRY.total_seconds():
            await self._async_fetch([radar_id])
        return self.products.get(radar_id)

    async def _async_poll(self, _now: dt.datetime | None = None) -> None:
        cutoff = monotonic() - RADAR_IDLE_AFTER.total_seconds()
        for rid in [r for r, t in self._needed.items() if t < cutoff]:
            self._needed.pop(rid, None)
            self.products.pop(rid, None)      # free memory for radars nobody needs
            self._raw_latest.pop(rid, None)
        await self.async_ensure_sites()
        if self._needed and await self._async_fetch(list(self._needed)):
            self._notify()

    async def _async_fetch(self, radar_ids: list[int]) -> bool:
        """Download new frames for these radars. True if any product changed."""
        async with self._lock:
            now = monotonic()
            if now < self._retry_after:
                return False
            for rid in radar_ids:
                self._last_try[rid] = now
            by_id = {s["id"]: s for s in self.registry}
            wanted = [rid for rid in radar_ids if rid in by_id]
            if not wanted:
                return False
            have = {rid: list(self.products[rid]["times"]) for rid in wanted if rid in self.products}
            try:
                fetched = await self.hass.async_add_executor_job(self._fetch_blocking, wanted, have)
            except Exception as err:  # noqa: BLE001 - FTP errors of every kind
                self._failed(str(err))
                return False
            self.last_poll = dt_util.utcnow()
            self._succeeded()
            changed = False
            for rid, (frames, raw) in fetched.items():
                old = self.products.get(rid)
                levels = list(old["levels"]) if old else []
                times = list(old["times"]) if old else []
                for t, lv in frames:
                    levels.append(lv)
                    times.append(t)
                if not times:
                    continue
                self.products[rid] = await self.hass.async_add_executor_job(
                    build_product, levels, times, by_id[rid], self.range_code, self.settings)
                if raw:
                    self._raw_latest[rid] = raw
                changed = True
            return changed

    def _fetch_blocking(self, radar_ids: list[int], have: dict[int, list]) -> dict:
        """FTP work (runs in the executor). Returns {rid: ([(time, levels)], newest_png)}."""
        out: dict[int, tuple[list, bytes | None]] = {}
        ftp = bom.connect()
        try:
            listing = bom.list_frames(ftp, radar_ids, self.range_code)
            for rid in radar_ids:
                known = {int(t.timestamp()) for t in have.get(rid, [])}
                new = [(t, n) for t, n in listing.get(rid, []) if int(t.timestamp()) not in known]
                new = new[-self.settings.history_frames:]
                frames, raw = [], None
                for t, name in new:
                    raw = bom.fetch(ftp, name)
                    frames.append((t, bom.decode_png(raw)))
                if frames:
                    out[rid] = (frames, raw)
        finally:
            bom._quit(ftp)  # noqa: SLF001
        return out

    def _failed(self, message: str) -> None:
        self._failures += 1
        self.last_error = message
        # 5, 10, 20, 40 then 60 minutes between attempts while BoM can't be reached.
        wait = min(RADAR_POLL.total_seconds() * 2 ** (self._failures - 1), 3600)
        self._retry_after = monotonic() + wait
        _LOGGER.warning("BoM radar download failed (%d in a row): %s", self._failures, message)
        if self._failures == ISSUE_AFTER_FAILURES:
            ir.async_create_issue(
                self.hass, DOMAIN, "radar_unavailable", is_fixable=False,
                severity=ir.IssueSeverity.WARNING, translation_key="radar_unavailable",
                translation_placeholders={"error": message[:200]})

    def _succeeded(self) -> None:
        if self._failures >= ISSUE_AFTER_FAILURES:
            ir.async_delete_issue(self.hass, DOMAIN, "radar_unavailable")
        self._failures = 0
        self._retry_after = 0.0
        self.last_error = None

    # ------------------------------------------------------------------ Open-Meteo fallback
    async def async_open_meteo(self, lat: float, lon: float) -> dict:
        cell = (round(lat / FALLBACK_CELL_DEG), round(lon / FALLBACK_CELL_DEG))
        lock = self._fallback_locks.setdefault(cell, asyncio.Lock())
        async with lock:
            hit = self._fallback.get(cell)
            if hit and hit[0] > monotonic():
                return hit[1]
            session = async_get_clientsession(self.hass)
            async with asyncio.timeout(15):
                resp = await session.get(openmeteo.URL, params=openmeteo.params(lat, lon, self.settings))
                resp.raise_for_status()
                data = await resp.json()
            self._fallback[cell] = (monotonic() + FALLBACK_CACHE.total_seconds(), data)
            now = monotonic()
            for k in [k for k, v in self._fallback.items() if v[0] < now]:
                self._fallback.pop(k, None)
            return data

    # ------------------------------------------------------------------ diagnostics
    async def async_diagnostics(self) -> dict[str, Any]:
        radars = {}
        for rid, p in self.products.items():
            vx, vy = p["motion"]["global"]
            info = {
                "frames": len(p["times"]),
                "latest_frame": p["times"][-1].isoformat(),
                "motion_px_per_min": [round(vx, 2), round(vy, 2)],
                "tiles_with_motion": p["motion"]["tiles_with_motion"],
            }
            raw = self._raw_latest.get(rid)
            if raw:
                info["palette_check"] = await self.hass.async_add_executor_job(bom.palette_report, raw)
            radars[f"IDR{rid:02d}{self.range_code}"] = info
        return {
            "radar_sites": len(self.registry),
            "radar_sites_updated": self.registry_updated.isoformat() if self.registry_updated else None,
            "radars_in_use": sorted(self._needed),
            "last_poll": self.last_poll.isoformat() if self.last_poll else None,
            "consecutive_failures": self._failures,
            "retry_in_seconds": max(0, round(self._retry_after - monotonic())),
            "last_error": self.last_error,
            "radars": radars,
        }
