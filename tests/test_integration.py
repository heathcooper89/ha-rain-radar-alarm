"""Run the integration inside Home Assistant with BoM's FTP server and Open-Meteo faked."""
from __future__ import annotations

import asyncio
import datetime as dt
import io
from pathlib import Path
import re
from unittest.mock import patch

import numpy as np
from PIL import Image
import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry, async_capture_events, async_fire_time_changed,
)

from custom_components.rain_radar_alarm.const import DOMAIN, EVENT
from custom_components.rain_radar_alarm.engine import bom
from custom_components.rain_radar_alarm.diagnostics import async_get_config_entry_diagnostics

from .test_engine import make_dbf

HOME = (-37.81, 144.96)                 # Melbourne CBD, ~19 km from the Laverton radar
SITE = (-37.8553, 144.7554)
PERTH = (-31.95, 115.86)                # no radar in the fake table -> Open-Meteo
OM_RE = re.compile(r"https://api\.open-meteo\.com/v1/forecast.*")

DBF = make_dbf([("Melbourne", str(SITE[1]), str(SITE[0]), "2", "Melbourne (Laverton)")],
               [("Name", 20), ("Longitude", 12), ("Latitude", 12), ("Radar_id", 4), ("Full_Name", 40)])


def png(levels: np.ndarray) -> bytes:
    rgba = np.zeros((*levels.shape, 4), dtype=np.uint8)
    for i, (colour, _) in enumerate(bom.PALETTE, start=1):
        rgba[levels == i] = (*colour, 255)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG")
    return buf.getvalue()


def storm_files(now: dt.datetime) -> dict[str, bytes]:
    """Six frames of a rain band 30 km west of home, moving east at 60 km/h."""
    rng = np.random.default_rng(4)
    tex = rng.integers(4, 9, size=(512, 512), dtype=np.uint8)
    latest = now.replace(second=0, microsecond=0) - dt.timedelta(minutes=2)
    files = {}
    for k in range(6):
        t = latest - dt.timedelta(minutes=6 * (5 - k))
        x0 = 182 - 12 * (5 - k)
        lv = np.zeros((512, 512), dtype=np.uint8)
        lv[140:360, x0:x0 + 50] = tex[140:360, 100:150]
        files[f"IDR023.T.{t:%Y%m%d%H%M}.png"] = png(lv)
    return files


class FakeFTP:
    """Just enough of ftplib.FTP for the radar manager."""

    files: dict[str, bytes] = {}
    fail = False
    retrieved: list[str] = []

    def __init__(self, *a, **k):
        if FakeFTP.fail:
            raise OSError("connection refused")

    def login(self):
        pass

    def cwd(self, path):
        pass

    def nlst(self, pattern=None):
        names = list(FakeFTP.files)
        if pattern:
            rx = re.compile("^" + re.escape(pattern).replace(r"\*", ".*") + "$")
            names = [n for n in names if rx.match(n)]
        if not names:
            import ftplib
            raise ftplib.error_perm("550 No files found")
        return names

    def retrbinary(self, cmd, callback):
        name = cmd.split(" ", 1)[1]
        if name != "IDR00007.dbf" and name not in FakeFTP.files:
            import ftplib
            raise ftplib.error_perm("550 Failed to open file")
        FakeFTP.retrieved.append(name)
        callback(FakeFTP.files.get(name, DBF))

    def quit(self):
        pass

    def close(self):
        pass


@pytest.fixture(autouse=True)
def fake_bom():
    FakeFTP.files = storm_files(dt_util.utcnow())
    FakeFTP.fail = False
    FakeFTP.retrieved = []
    with patch("custom_components.rain_radar_alarm.engine.bom.ftplib.FTP", FakeFTP):
        yield FakeFTP


def om_payload():
    now = dt_util.utcnow().replace(second=0, microsecond=0)
    base = now - dt.timedelta(minutes=now.minute % 15)
    times = [(base + dt.timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M") for i in range(-2, 10)]
    precip = [0, 0, 0, 0, 0.5, 0.8, 0.4, 0, 0, 0, 0, 0]
    hours = [(base.replace(minute=0) + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(-1, 4)]
    return {"minutely_15": {"time": times, "precipitation": precip},
            "hourly": {"time": hours, "precipitation_probability": [20, 70, 70, 30, 10]}}


async def _setup(hass, aioclient_mock, people=None, options=None):
    hass.config.latitude, hass.config.longitude = HOME
    hass.config.location_name = "Home"
    await async_setup_component(hass, "zone", {})
    for pid, (state, attrs) in (people or {}).items():
        hass.states.async_set(pid, state, attrs)
    aioclient_mock.get(OM_RE, json=om_payload())
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options or {})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


def why(entry) -> str:
    """Radar state to show when an assertion fails."""
    m = entry.runtime_data.manager
    return f"sites={len(m.registry)} products={list(m.products)} error={m.last_error} ftp={FakeFTP.retrieved}"


def eid(hass, entry, loc, key, domain="sensor"):
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{loc}_{key}")


async def test_config_flow_requires_terms(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    base = {"include_home": True, "persons": [], "soon_minutes": 20, "radar_range": "3",
            "fallback": True, "alert_probability": 50, "rain_threshold": 0.2}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**base, "accept_terms": False})
    assert result["errors"] == {"accept_terms": "terms_required"}
    with patch("custom_components.rain_radar_alarm.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {**base, "accept_terms": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["soon_minutes"] == 20 and "accept_terms" not in result["options"]
    # Only one instance.
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert again["type"] is FlowResultType.ABORT and again["reason"] == "single_instance_allowed"


async def test_home_and_people(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup(hass, aioclient_mock, people={
        "person.heath": ("home", {"friendly_name": "Heath"}),                       # at home, no GPS
        "person.sam": ("not_home", {"latitude": PERTH[0], "longitude": PERTH[1], "friendly_name": "Sam"}),
        "person.alex": ("not_home", {"friendly_name": "Alex"}),                     # unknown location
    })
    status = hass.states.get(eid(hass, entry, "home", "status"))
    assert status.state == "rain_expected", status.attributes
    assert status.attributes["summary"].startswith(("Moderate", "Heavy"))
    minutes = int(hass.states.get(eid(hass, entry, "home", "minutes_until_rain")).state)
    assert 20 <= minutes <= 40, why(entry)
    assert hass.states.get(eid(hass, entry, "home", "rain_soon", "binary_sensor")).state == "off", why(entry)
    src = hass.states.get(eid(hass, entry, "home", "data_source"))
    assert src.state == "radar" and src.attributes["radar_id"] == "IDR023", why(entry)
    assert "Bureau of Meteorology" in src.attributes["attribution"]

    # Heath is at home: same answer, and the radar frames were downloaded once only.
    assert hass.states.get(eid(hass, entry, "heath", "status")).state == "rain_expected"
    frames = [n for n in FakeFTP.retrieved if ".T." in n]
    assert len(frames) == len(set(frames)) == 6

    # Sam is in Perth: no radar in the table, so the Open-Meteo fallback answers.
    sam = hass.states.get(eid(hass, entry, "sam", "data_source"))
    assert sam.state == "model" and "Open-Meteo" in sam.attributes["attribution"]
    assert hass.states.get(eid(hass, entry, "sam", "status")).state == "rain_expected"

    # Alex has no location.
    assert hass.states.get(eid(hass, entry, "alex", "status")).state == "unavailable"


async def test_rain_soon_uses_option(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup(hass, aioclient_mock, options={"soon_minutes": 45})
    soon = hass.states.get(eid(hass, entry, "home", "rain_soon", "binary_sensor"))
    assert soon.state == "on" and soon.attributes["within_minutes"] == 45


async def test_no_fallback_means_unavailable(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup(hass, aioclient_mock, options={"fallback": False}, people={
        "person.sam": ("not_home", {"latitude": PERTH[0], "longitude": PERTH[1], "friendly_name": "Sam"})})
    assert hass.states.get(eid(hass, entry, "sam", "status")).state == "unavailable"
    assert not any("open-meteo" in str(c[1]) for c in aioclient_mock.mock_calls)


async def test_moving_person_and_events(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup(hass, aioclient_mock, people={
        "person.sam": ("not_home", {"latitude": PERTH[0], "longitude": PERTH[1], "friendly_name": "Sam"})})
    events = async_capture_events(hass, EVENT)
    assert hass.states.get(eid(hass, entry, "sam", "data_source")).state == "model"
    # Sam flies to Melbourne and lands inside the rain band.
    lat, lon = -37.80, 144.62
    hass.states.async_set("person.sam", "not_home", {"latitude": lat, "longitude": lon, "friendly_name": "Sam"})
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + dt.timedelta(seconds=15))
    await hass.async_block_till_done()
    assert hass.states.get(eid(hass, entry, "sam", "data_source")).state == "radar", why(entry)
    assert hass.states.get(eid(hass, entry, "sam", "raining", "binary_sensor")).state == "on"
    assert events and events[-1].data["person"] == "person.sam"
    assert events[-1].data["previous_status"] == "rain_expected"


async def test_radar_outage_repair_issue(hass: HomeAssistant, aioclient_mock) -> None:
    FakeFTP.fail = True
    entry = await _setup(hass, aioclient_mock)
    # BoM down from the start: no radar table either, so home falls back to Open-Meteo.
    assert hass.states.get(eid(hass, entry, "home", "data_source")).state == "model"
    manager = entry.runtime_data.manager
    manager.registry = [{"id": 2, "name": "Melbourne (Laverton)", "lat": SITE[0], "lon": SITE[1]}]
    for _ in range(3):
        manager._retry_after = 0
        await manager._async_fetch([2])
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, "radar_unavailable") is not None
    # Backing off: the next attempt waits (20 minutes after three failures).
    FakeFTP.fail = False
    assert not await manager._async_fetch([2])
    assert 19 * 60 < manager._retry_after - __import__("time").monotonic() <= 20 * 60
    manager._retry_after = 0
    assert await manager._async_fetch([2])
    assert issues.async_get_issue(DOMAIN, "radar_unavailable") is None


async def test_diagnostics(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup(hass, aioclient_mock, people={
        "person.heath": ("home", {"friendly_name": "Heath"})})
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert "IDR023" in diag["radar"]["radars"], why(entry)
    radar = diag["radar"]["radars"]["IDR023"]
    assert radar["frames"] == 6
    assert radar["palette_check"]["opaque_pixels"] == radar["palette_check"]["matched_pixels"] > 0
    assert diag["people_tracked"] == 1
    assert "Heath" not in str(diag) and "heath" not in str(diag)


async def test_options_reload(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup(hass, aioclient_mock, people={"person.heath": ("home", {"friendly_name": "Heath"})})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "include_home": False, "persons": ["person.heath"], "soon_minutes": 15, "radar_range": "3",
        "fallback": True, "alert_probability": 60, "rain_threshold": 0.5})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert list(entry.runtime_data.coordinators) == ["person.heath"]
    assert entry.runtime_data.manager.settings.alert_probability == 0.6


async def test_blueprint_is_valid(hass: HomeAssistant) -> None:
    from homeassistant.components.automation.config import async_validate_config_item
    from homeassistant.components.blueprint.models import Blueprint, BlueprintInputs
    from homeassistant.components.blueprint.schemas import BLUEPRINT_SCHEMA
    from homeassistant.util.yaml import load_yaml_dict

    path = Path(__file__).parents[1] / "blueprints/automation/rain_radar_alarm/rain_notify.yaml"
    bp = Blueprint(load_yaml_dict(str(path)), expected_domain="automation", schema=BLUEPRINT_SCHEMA)
    inputs = BlueprintInputs(bp, {"use_blueprint": {"path": "rain_notify.yaml", "input": {
        "rain_soon": "binary_sensor.rain_radar_home_rain_soon",
        "status": "sensor.rain_radar_home_status",
        "notify_devices": ["abc123"]}}})
    inputs.validate()
    await async_setup_component(hass, "homeassistant", {})
    validated = await async_validate_config_item(hass, "test", inputs.async_substitute())
    assert validated is not None and validated.validation_error is None, validated.validation_error


async def test_server_without_name_patterns(hass: HomeAssistant, aioclient_mock) -> None:
    """If BoM's server refuses NLST patterns, one full listing is used instead."""
    real_nlst = FakeFTP.nlst

    def no_patterns(self, pattern=None):
        if pattern:
            import ftplib
            raise ftplib.error_perm("501 Syntax error")
        return real_nlst(self) + ["IDR713.T.202601010000.png", "readme.txt"]

    with patch.object(FakeFTP, "nlst", no_patterns):
        entry = await _setup(hass, aioclient_mock)
    assert hass.states.get(eid(hass, entry, "home", "data_source")).state == "radar", why(entry)


async def test_new_person_is_picked_up(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup(hass, aioclient_mock)
    assert list(entry.runtime_data.coordinators) == ["home"]
    hass.states.async_set("person.kim", "home", {"friendly_name": "Kim"})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert "person.kim" in entry.runtime_data.coordinators
    assert hass.states.get(eid(hass, entry, "kim", "status")).state == "rain_expected"


async def test_setup_does_not_wait_for_bom(hass: HomeAssistant, aioclient_mock) -> None:
    """Setup returns before any network work; forecasts follow in the background."""
    hass.config.latitude, hass.config.longitude = HOME
    await async_setup_component(hass, "zone", {})
    aioclient_mock.get(OM_RE, json=om_payload())
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    async def slow_bom(self) -> None:
        await asyncio.sleep(3600)

    with patch("custom_components.rain_radar_alarm.radar.RadarManager.async_ensure_sites", slow_bom):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is config_entries.ConfigEntryState.LOADED
        assert hass.states.get(eid(hass, entry, "home", "status")).state == "unavailable"
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_removal_deletes_saved_radar_list(hass: HomeAssistant, aioclient_mock, hass_storage) -> None:
    entry = await _setup(hass, aioclient_mock)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.radar_sites" in hass_storage
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert f"{DOMAIN}.radar_sites" not in hass_storage


async def test_first_download_right_after_boot(hass: HomeAssistant, aioclient_mock) -> None:
    """Just after the computer starts, the monotonic clock is near zero; radar must still load."""
    with patch("custom_components.rain_radar_alarm.radar.monotonic", return_value=30.0):
        entry = await _setup(hass, aioclient_mock)
        assert hass.states.get(eid(hass, entry, "home", "data_source")).state == "radar", why(entry)


def layer_png(rgba) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (512, 512), rgba).save(buf, "PNG")
    return buf.getvalue()


async def test_radar_map_camera(hass: HomeAssistant, aioclient_mock, hass_client) -> None:
    from homeassistant.components.camera import async_get_image

    FakeFTP.files["IDR023.background.png"] = layer_png((90, 140, 90, 255))   # BoM map layer (fake)
    entry = await _setup(hass, aioclient_mock, people={
        "person.sam": ("not_home", {"latitude": PERTH[0], "longitude": PERTH[1], "friendly_name": "Sam"})})
    cam = eid(hass, entry, "home", "radar_map", "camera")
    assert cam == "camera.rain_radar_home_radar_map"
    assert hass.states.get(cam).state == "idle"

    image = await async_get_image(hass, cam)
    assert image.content_type == "image/gif"
    gif = Image.open(io.BytesIO(image.content))
    assert gif.n_frames == 12 and gif.size == (400, 400)       # 6 recent + 6 forecast frames
    gif.seek(0)
    assert gif.convert("RGB").getpixel((5, 200)) == (90, 140, 90)  # map layer drawn under the rain

    # Drawn once: the second request reuses the loop and the map layers.
    again = await async_get_image(hass, cam)
    assert again.content == image.content
    assert FakeFTP.retrieved.count("IDR023.background.png") == 1
    assert "IDR023.topography.png" not in FakeFTP.retrieved    # layers BoM doesn't have are skipped

    # Sam is outside radar coverage: no radar map.
    assert hass.states.get(eid(hass, entry, "sam", "radar_map", "camera")).state == "unavailable"

    # Live view streams the frames one by one as JPEG.
    client = await hass_client()
    resp = await client.get(f"/api/camera_proxy_stream/{cam}")
    assert resp.status == 200
    chunk = await asyncio.wait_for(resp.content.read(4096), 5)
    assert b"Content-Type: image/jpeg" in chunk
    resp.close()


async def test_radar_map_without_map_layers(hass: HomeAssistant, aioclient_mock) -> None:
    from homeassistant.components.camera import async_get_image

    entry = await _setup(hass, aioclient_mock)
    image = await async_get_image(hass, eid(hass, entry, "home", "radar_map", "camera"))
    assert Image.open(io.BytesIO(image.content)).n_frames == 12
