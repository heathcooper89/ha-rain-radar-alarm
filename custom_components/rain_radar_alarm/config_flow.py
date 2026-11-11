"""Set-up and options screens."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ACCEPT_TERMS, CONF_ALERT_PROBABILITY, CONF_FALLBACK, CONF_INCLUDE_HOME, CONF_PERSONS,
    CONF_RADAR_RANGE, CONF_RAIN_THRESHOLD, CONF_SOON_MINUTES, DEFAULTS, DOMAIN,
)


def _schema(values: dict[str, Any], with_terms: bool) -> vol.Schema:
    v = {**DEFAULTS, **values}
    fields: dict = {
        vol.Required(CONF_INCLUDE_HOME, default=v[CONF_INCLUDE_HOME]): selector.BooleanSelector(),
        vol.Optional(CONF_PERSONS, default=v[CONF_PERSONS]): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="person", multiple=True)),
        vol.Required(CONF_SOON_MINUTES, default=v[CONF_SOON_MINUTES]): selector.NumberSelector(
            selector.NumberSelectorConfig(min=5, max=120, step=5, unit_of_measurement="min",
                                          mode=selector.NumberSelectorMode.SLIDER)),
        vol.Required(CONF_RADAR_RANGE, default=v[CONF_RADAR_RANGE]): selector.SelectSelector(
            selector.SelectSelectorConfig(options=["3", "2"], translation_key=CONF_RADAR_RANGE,
                                          mode=selector.SelectSelectorMode.LIST)),
        vol.Required(CONF_FALLBACK, default=v[CONF_FALLBACK]): selector.BooleanSelector(),
        vol.Required(CONF_ALERT_PROBABILITY, default=v[CONF_ALERT_PROBABILITY]): selector.NumberSelector(
            selector.NumberSelectorConfig(min=30, max=80, step=5, unit_of_measurement="%",
                                          mode=selector.NumberSelectorMode.SLIDER)),
        vol.Required(CONF_RAIN_THRESHOLD, default=v[CONF_RAIN_THRESHOLD]): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0.2, max=5, step=0.1, unit_of_measurement="mm/h",
                                          mode=selector.NumberSelectorMode.BOX)),
    }
    if with_terms:
        fields[vol.Required(CONF_ACCEPT_TERMS, default=False)] = selector.BooleanSelector()
    return vol.Schema(fields)


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in user_input.items() if k != CONF_ACCEPT_TERMS}
    out[CONF_SOON_MINUTES] = int(out[CONF_SOON_MINUTES])
    out[CONF_ALERT_PROBABILITY] = int(out[CONF_ALERT_PROBABILITY])
    out[CONF_RAIN_THRESHOLD] = float(out[CONF_RAIN_THRESHOLD])
    return out


class RainRadarAlarmConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_ACCEPT_TERMS):
                errors[CONF_ACCEPT_TERMS] = "terms_required"
            else:
                return self.async_create_entry(title="Rain Radar Alarm", data={},
                                               options=_clean(user_input))
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}, True),
                                    errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return RainRadarAlarmOptionsFlow()


class RainRadarAlarmOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=_clean(user_input))
        return self.async_show_form(step_id="init",
                                    data_schema=_schema(dict(self.config_entry.options), False))
