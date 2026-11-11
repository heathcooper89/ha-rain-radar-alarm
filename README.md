# Rain Radar Alarm

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Validate](https://github.com/heathcooper89/ha-rain-radar-alarm/actions/workflows/validate.yml/badge.svg)](https://github.com/heathcooper89/ha-rain-radar-alarm/actions/workflows/validate.yml)
[![Tests](https://github.com/heathcooper89/ha-rain-radar-alarm/actions/workflows/tests.yml/badge.svg)](https://github.com/heathcooper89/ha-rain-radar-alarm/actions/workflows/tests.yml)

A Home Assistant custom integration that warns you before it rains, at home and wherever each person in your household is. It reads Australian Bureau of Meteorology (BoM) rain radar, works out which way the rain is moving, and tells you whether rain is coming, how heavy, how many minutes away, and when it will clear.

All the work happens inside Home Assistant. There is no server to run, no account and no API key.

Tested with Home Assistant 2026.2. The integration icon shows from Home Assistant 2026.3.

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

Everyone under one radar shares one download and one motion calculation. A person moving more than 750 m gets a new forecast straight away.

**Accuracy:** this is extrapolation. It's reliable for about 30 minutes, reasonable to an hour, and a rough guide after that. It assumes rain keeps its strength, so showers and storms that form or fade within the hour are its weak spot. Steady rain bands are its strong suit.

## Phone notifications

A blueprint is included. Copy `blueprints/automation/rain_radar_alarm/rain_notify.yaml` to `config/blueprints/automation/rain_radar_alarm/`, reload automations, then create an automation from **Rain Radar Alarm – phone notifications**. Make one for home and one per person.

## Data sources and licences

**This integration contains no weather data.** Each Home Assistant that installs it downloads data directly from the source, for its own household. Nothing passes through, or is stored by, anyone else.

- **Bureau of Meteorology radar images and radar locations**, from BoM's [anonymous FTP service](https://www.bom.gov.au/catalogue/anon-ftp.shtml). Under the default terms of [BoM's copyright notice](https://www.bom.gov.au/copyright), you may download and use this material for personal use or within your organisation. You may **not** supply it to anyone else or use it for any commercial purpose. Publishing BoM data requires registering with BoM. This integration keeps radar images in memory only, never saves or re-publishes them, and shows the attribution "Radar data © Bureau of Meteorology" on its entities. If you want to use radar data commercially, talk to BoM about its registered-user services.
- **Open-Meteo** forecast API (used only outside radar coverage, and only if you leave it on). Free for non-commercial use, with data under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Commercial use needs an Open-Meteo subscription. Attribution: "Weather data by Open-Meteo.com".

This project is not affiliated with, or endorsed by, the Bureau of Meteorology or Open-Meteo. It does not use their names or logos as branding.

**What leaves your Home Assistant:**
- FTP requests to `ftp.bom.gov.au` for radar images, which carry no location information.
- Only when the fallback is used, a request to `api.open-meteo.com` with the location rounded to 2 decimal places (about 1 km).

**Being a good neighbour:** BoM asks users to consider how often its products update. This integration downloads each new frame once, checks every 5 minutes (BoM publishes every 5 to 10 minutes), fetches only the radars in use, and backs off by itself when BoM can't be reached.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Data source shows *Open-Meteo model* near a BoM radar | Home Assistant can't reach `ftp.bom.gov.au`, or BoM has changed its service. A repair notice appears after three failed downloads in a row. Check the log for `rain_radar_alarm`. |
| Says *Dry* while the BoM website shows rain at that spot | Download diagnostics (Settings → Devices & services → Rain Radar Alarm → ⋮ → Download diagnostics). Under `palette_check`, `matched_pixels` should equal `opaque_pixels` on a rainy day. If it doesn't, please open an issue with that section attached. |
| Every location shows *Open-Meteo model*, and diagnostics show `radar_sites: 0` | BoM's radar locations table couldn't be read. It's retried weekly and on restart; please open an issue if it persists. |
| A person's sensors are *unavailable* | Home Assistant has no location for them. Set their Companion app's location permission to Always. |
| Warnings arrive too late or too early | Lower or raise *Rain alert sensitivity*. |

Diagnostics files round locations to about 10 km and leave out people's names, so they're safe to attach to an issue.

## Development

```bash
pip install -r requirements_test.txt
pytest
```

The tests run the integration inside Home Assistant with a fake BoM FTP server serving a synthetic storm, and a faked Open-Meteo. They cover setup, the terms confirmation, people at home, away and without a location, a person moving into the rain, the fallback, a BoM outage and its repair notice, diagnostics, options, and the blueprint. Engine tests check motion recovery and arrival and clearing times on storms of known speed.

`docs/icon-options/generate_icons.py` draws the icon options; `--brand B` writes the chosen icon (option B, Radar scope) into `brand/`; A, C or D work the same way.

## Licence

Code: [MIT](LICENSE). Weather data: see *Data sources and licences*; the MIT licence does not cover data you download from BoM or Open-Meteo.
