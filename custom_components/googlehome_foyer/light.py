from __future__ import annotations

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FoyerConfigEntry, FoyerEntity, add_devices
from .api import bool_wrapper, num_wrapper


async def async_setup_entry(
    hass: HomeAssistant, entry: FoyerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    add_devices(entry, async_add_entities, Platform.LIGHT, FoyerLight)


class FoyerLight(FoyerEntity, LightEntity):
    # ponytail: no RGB; foyer color writes beyond colorTemperature aren't captured yet.
    _attr_min_color_temp_kelvin = 2000
    _attr_max_color_temp_kelvin = 6500

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device)
        if "color_temperature" in device.caps:
            mode = ColorMode.COLOR_TEMP
        elif "brightness" in device.caps:
            mode = ColorMode.BRIGHTNESS
        else:
            mode = ColorMode.ONOFF
        self._attr_color_mode = mode
        self._attr_supported_color_modes = {mode}

    @property
    def is_on(self) -> bool | None:
        return self.state_data.on

    @property
    def brightness(self) -> int | None:
        pct = self.state_data.brightness
        return None if pct is None else round(pct * 255 / 100)

    @property
    def color_temp_kelvin(self) -> int | None:
        k = self.state_data.color_temp_k
        return None if k is None else int(k)

    async def async_turn_on(self, **kwargs) -> None:
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            await self._update(
                "color", [("colorTemperature", num_wrapper(int(kwargs[ATTR_COLOR_TEMP_KELVIN])))]
            )
        if ATTR_BRIGHTNESS in kwargs:
            pct = max(1, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255))
            await self._update("brightness", [("brightness", num_wrapper(pct))])
        if not self.is_on or not kwargs:
            await self._update("onOff", [("onOff", bool_wrapper(True))])

    async def async_turn_off(self, **kwargs) -> None:
        await self._update("onOff", [("onOff", bool_wrapper(False))])
