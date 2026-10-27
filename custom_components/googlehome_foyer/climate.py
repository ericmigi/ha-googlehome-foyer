from __future__ import annotations

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    PRESET_ECO,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, Platform, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FoyerConfigEntry, FoyerEntity, add_devices

TO_HA = {"off": HVACMode.OFF, "heat": HVACMode.HEAT, "cool": HVACMode.COOL, "heatcool": HVACMode.HEAT_COOL}
TO_GOOGLE = {v: k for k, v in TO_HA.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: FoyerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    add_devices(entry, async_add_entities, Platform.CLIMATE, FoyerClimate)


class FoyerClimate(FoyerEntity, ClimateEntity):
    """Single-setpoint thermostat. Google's `eco` mode is exposed as the eco preset."""

    # ponytail: heatcool range setpoints not captured; HEAT_COOL is mode-only.
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = list(TO_GOOGLE)
    _attr_preset_modes = [PRESET_NONE, PRESET_ECO]
    _attr_target_temperature_step = 0.5
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _last_mode = HVACMode.HEAT

    @property
    def hvac_mode(self) -> HVACMode | None:
        mode = self.state_data.mode
        if mode in TO_HA:
            if mode != "off":
                self._last_mode = TO_HA[mode]
            return TO_HA[mode]
        return self._last_mode if mode == "eco" else None

    @property
    def preset_mode(self) -> str:
        return PRESET_ECO if self.state_data.mode == "eco" else PRESET_NONE

    @property
    def current_temperature(self) -> float | None:
        return self.state_data.ambient_c

    @property
    def target_temperature(self) -> float | None:
        return None if self.state_data.mode in ("off", "eco", "heatcool") else self.state_data.setpoint_c

    async def _set(self, setpoint_c: float | None, mode: str | None) -> None:
        await self._apply(
            self.coordinator.client.set_thermostat(self.device, setpoint_c, mode)
        )

    async def async_set_temperature(self, **kwargs) -> None:
        mode = TO_GOOGLE.get(kwargs[ATTR_HVAC_MODE]) if ATTR_HVAC_MODE in kwargs else None
        if (mode or self.state_data.mode) in ("off", "eco", "heatcool"):
            raise HomeAssistantError("Set heat or cool mode before setting a temperature.")
        await self._set(kwargs.get(ATTR_TEMPERATURE), mode)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self._set(None, TO_GOOGLE[hvac_mode])

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._set(None, "eco" if preset_mode == PRESET_ECO else TO_GOOGLE[self._last_mode])

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(self._last_mode)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
