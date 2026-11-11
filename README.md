# Rain Radar Alarm

<img src="https://raw.githubusercontent.com/heathcooper89/ha-rain-radar-alarm/main/custom_components/rain_radar_alarm/brand/icon.png" alt="Rain Radar Alarm icon" width="96" align="right">

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Validate](https://github.com/heathcooper89/ha-rain-radar-alarm/actions/workflows/validate.yml/badge.svg)](https://github.com/heathcooper89/ha-rain-radar-alarm/actions/workflows/validate.yml)
[![Tests](https://github.com/heathcooper89/ha-rain-radar-alarm/actions/workflows/tests.yml/badge.svg)](https://github.com/heathcooper89/ha-rain-radar-alarm/actions/workflows/tests.yml)

A Home Assistant custom integration that warns you before it rains, at home and wherever each person in your household is. It reads Australian Bureau of Meteorology (BoM) rain radar, works out which way the rain is moving, and tells you whether rain is coming, how heavy, how many minutes away, and when it will clear.

All the work happens inside Home Assistant. There is no server to run, no account and no API key.

Needs Home Assistant 2026.2 or newer; tested on 2026.2 and 2026.10. Home Assistant shows the integration's icon from 2026.3.

## What you get

One device for your home and one per person, each with:

| Entity | Example |
|---|---|
| `sensor.rain_radar_<who>_status` | Dry, Rain expected, Raining, Clearing, Cleared. Its `summary` attribute reads like *"Heavy rain in about 25 min, clearing around 15:40"* |
| `sensor.…_minutes_until_rain`, `…_minutes_until_clear` | minutes |
| `sensor.…_rain_starts`, `…_rain_clears` | times (shown as "in 25 minutes") |
| `sensor.…_rain_rate`, `…_peak_rain_rate` | mm/h |
| `sensor.…_intensity` | None, Light, Moderate, Heavy, Intense |
| `binary_sensor.…_raining` | on while it's raining there |
| `binary_sensor.…_rain_soon` | on when it's raining or rain is due within your warning time |
| `camera.rain_radar_<who>_radar_map` | a radar map centred on that place: the last hour of radar, then a forecast out to an hour ahead (see *Radar map*) |
| `sensor.…_data_source` (diagnostic) | BoM radar or Open-Meteo model, with the radar's name |
| `sensor.…_radar_data_age` (diagnostic) | minutes since the radar image was taken |

Each status change fires a `rain_radar_alarm_event` with `person`, `status`, `previous_status`, `minutes_until_rain`, `minutes_until_clear` and `summary`.

Intensity bands: light below 2.5 mm/h, moderate below 10, heavy below 50, intense from 50.

## Install

**Marketplace (Home Assistant 2026.11 and newer) or HACS:**

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=heathcooper89&repository=ha-rain-radar-alarm&category=integration)

Or add it yourself:

- **Home Assistant 2026.11 and newer:** Settings → Marketplace → **Add from link**, and enter `https://github.com/heathcooper89/ha-rain-radar-alarm`.
- **Older versions with HACS:** HACS → ⋮ → Custom repositories, add `https://github.com/heathcooper89/ha-rain-radar-alarm` with type Integration.

Download Rain Radar Alarm, then restart Home Assistant.

**Manual:** copy `custom_components/rain_radar_alarm` from the [latest release](https://github.com/heathcooper89/ha-rain-radar-alarm/releases) into `/config/custom_components/`, then restart Home Assistant.

Then go to Settings → Devices & services → Add integration → **Rain Radar Alarm**.

## Settings

| Setting | What it does |
|---|---|
| Track my home | A device for your Home Assistant home location. |
| People to track | Leave empty for everyone, including people added later. |
| "Rain soon" warning time | Rain soon turns on when rain is this close. Default 30 minutes. |
| Radar range | 128 km images (0.5 km detail, default) or 256 km (1 km detail, sees rain from further away). |
| Use Open-Meteo outside radar coverage | A free model forecast for places more than about 120 km from a BoM radar. On by default. |
| Rain alert sensitivity | How much of the area around a location must be forecast to have rain. Lower warns earlier, with more false alarms. Default 50%. |
| Lightest rain to count | Rain below this is ignored. Default 0.2 mm/h, the lightest BoM radar shows. |

All of them can be changed later via **Configure** on the integration. During setup you're asked to confirm you'll use BoM data for personal, non-commercial use (see *Data sources and licences*).

People are followed using their phone's location from the Home Assistant Companion app, or the centre of the zone they're in. For people to be followed outside zones, their app needs location permission set to **Always**.

## How it works

1. **Radar locations:** BoM's own radar site table (`IDR00007.dbf` on its public FTP service) is read once a week and kept in Home Assistant's storage.
2. **Which radar:** each location uses the nearest radar whose image covers it.
3. **Downloads:** every 5 minutes, Home Assistant downloads only the new frames of the radars in use, over one FTP connection. A radar nobody has needed for 6 hours is dropped.
4. **Motion:** for each radar, the last few frames show how the rain is moving: speed and direction in 128-pixel tiles, so a front and a storm cell 100 km apart can move differently. This is done once per radar per new frame.
5. **Forecast:** each location traces the air arriving at it back along that motion and reads the latest radar there, every 5 minutes out to 2 hours, in a circle that widens with time to allow for uncertainty. About 2 ms per location.
6. **Fallback:** if no radar covers a place, or BoM can't be reached, the Open-Meteo 15-minute forecast is used if you've left it on.
7. **Radar map:** drawn only when someone looks at it, from frames already downloaded, and reused until BoM publishes a new frame.

Everyone under one radar shares one download and one motion calculation. A person moving more than 750 m gets a new forecast straight away.

**Accuracy:** this is extrapolation. It's reliable for about 30 minutes, reasonable to an hour, and a rough guide after that. It assumes rain keeps its strength, so showers and storms that form or fade within the hour are its weak spot. Steady rain bands are its strong suit.

## Radar map

Each place gets a **Radar map** camera, about 100 km across (200 km with the 256 km radar range), centred on the coral dot:
- up to an hour of recent radar, each frame labelled with its time
- then forecast frames 10 to 60 minutes ahead, labelled in yellow, showing where today's rain is moving

Forecast frames move the latest radar along the storm's motion, so they show where existing rain is heading, not showers that will form or fade.

Use a Picture entity card for a dashboard. The camera's picture is an animated GIF, and its live view plays the same frames one by one. The map underneath uses BoM's own map layers for each radar (land, topography, range rings and town names). These come from the same FTP service and are downloaded once a week.

The camera is unavailable when a place is outside radar coverage or BoM can't be reached.

## Phone notifications

A blueprint is included. Copy `blueprints/automation/rain_radar_alarm/rain_notify.yaml` to `config/blueprints/automation/rain_radar_alarm/`, reload automations, then create an automation from **Rain Radar Alarm – phone notifications**. Make one for home and one per person.

To include the radar map in the "rain soon" notification, pick that place's Radar map camera in the blueprint. Only send it to your own household's phones through the Home Assistant Companion app (see *Data sources and licences*).

## Data sources and licences

**This integration contains no weather data.** Each Home Assistant that installs it downloads data directly from the source, for its own household. Nothing passes through, or is stored by, anyone else.

- **Bureau of Meteorology radar images and radar locations**, from BoM's [anonymous FTP service](https://www.bom.gov.au/catalogue/anon-ftp.shtml). Everything on that service is covered by the default terms of [BoM's copyright notice](https://www.bom.gov.au/copyright): you *"may download, use and copy that material for personal use, or use within your organisation but you may not supply that material to any other person or use it for any commercial purpose."* BoM also says *"Users intending to publish Bureau data should do so as Registered Users."*
  - This integration keeps radar images and BoM's map layers in memory only, never saves or re-publishes them, and credits "© Bureau of Meteorology" on its entities and on every radar map frame.
  - The radar map is only served to people logged in to your Home Assistant. Companion app notifications fetch it straight from your own Home Assistant.
  - Keep it that way. Don't send the radar map to people outside your household or through services that keep a copy (Telegram, email, Discord and the like). Don't save it into `config/www`, which Home Assistant serves without a login. Don't post screenshots of real radar publicly.
  - You confirm personal, non-commercial use when you add the integration.
  - For commercial use or publishing, talk to BoM about its registered-user services.
- **Open-Meteo** forecast API (used only outside radar coverage, and only if you leave it on). Free for non-commercial use, with data under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Commercial use needs an Open-Meteo subscription. Attribution: "Weather data by Open-Meteo.com".

This project is not affiliated with, or endorsed by, the Bureau of Meteorology or Open-Meteo. It does not use their names or logos as branding.

**What leaves your Home Assistant:**
- FTP requests to `ftp.bom.gov.au` for radar images and map layers, which carry no location information.
- Only when the fallback is used, a request to `api.open-meteo.com` with the location rounded to 2 decimal places (about 1 km).

**Light on BoM's servers:** it uses BoM's published FTP service, not the BoM website.
- It checks every 5 minutes; BoM publishes a new frame every 5 to 10 minutes.
- It fetches only the radars someone is near, and downloads each frame once.
- It reads the radar locations table, and each radar's map layers, once a week.
- Drawing the radar map uses no extra downloads beyond the weekly map layers.
- When BoM can't be reached, it waits 5, 10, 20 and then 40 minutes between tries, then once an hour.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Data source shows *Open-Meteo model* near a BoM radar | Home Assistant can't reach `ftp.bom.gov.au`, or BoM has changed its service. A repair notice appears after three failed downloads in a row. Check the log for `rain_radar_alarm`. |
| Says *Dry* while the BoM website shows rain at that spot | Download diagnostics (Settings → Devices & services → Rain Radar Alarm → ⋮ → Download diagnostics). Under `palette_check`, `matched_pixels` should equal `opaque_pixels` on a rainy day. If it doesn't, please open an issue with that section attached. |
| Every location shows *Open-Meteo model*, and diagnostics show `radar_sites: 0` | BoM's radar locations table couldn't be read. It's retried weekly and on restart; please open an issue if it persists. |
| Radar map has no land, towns or range rings | BoM's map layers couldn't be read. It's retried hourly. Diagnostics list the layers it has under `map_layers`. |
| A person's sensors are *unavailable* | Home Assistant has no location for them. Set their Companion app's location permission to Always. |
| Warnings arrive too late or too early | Lower or raise *Rain alert sensitivity*. |

Diagnostics files round locations to about 10 km and leave out people's names, so they're safe to attach to an issue.

## Removing

Settings → Devices & services → Rain Radar Alarm → ⋮ → **Delete**. This also deletes the saved radar locations. Then remove it in HACS or the Marketplace (or delete `custom_components/rain_radar_alarm`) and restart Home Assistant. If you copied the blueprint, delete it from `config/blueprints/automation/rain_radar_alarm/`.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

The tests run the integration inside Home Assistant against a fake BoM FTP server serving a synthetic storm, and a fake Open-Meteo. They cover:
- setup and the terms confirmation, including that setup doesn't wait for BoM
- people at home, away, without a location, added later, and moving into the rain
- the radar map camera, with and without BoM's map layers, and its live view
- the fallback, a BoM outage with its repair notice and back-off
- diagnostics, options, removal, and the blueprint

Engine tests check motion recovery, arrival and clearing times on storms of known speed, and that forecast map frames move rain at the storm's speed.

The icon's source is `docs/icon/icon.svg`. `python3 docs/icon/generate_icon.py` redraws it and writes `brand/icon.png` and `brand/icon@2x.png`; it needs Playwright with Chromium.

## Licence

Code: [MIT](LICENSE). Weather data: see *Data sources and licences*; the MIT licence does not cover data you download from BoM or Open-Meteo.
