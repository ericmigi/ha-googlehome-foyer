from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FoyerConfigEntry, FoyerEntity, add_devices
from .api import bool_wrapper


async def async_setup_entry(
    hass: HomeAssistant, entry: FoyerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    add_devices(entry, async_add_entities, Platform.SWITCH, FoyerSwitch)


class FoyerSwitch(FoyerEntity, SwitchEntity):
    @property
    def is_on(self) -> bool | None:
        return self.state_data.on

    async def async_turn_on(self, **kwargs) -> None:
        await self._update("onOff", [("onOff", bool_wrapper(True))])

    async def async_turn_off(self, **kwargs) -> None:
        await self._update("onOff", [("onOff", bool_wrapper(False))])
