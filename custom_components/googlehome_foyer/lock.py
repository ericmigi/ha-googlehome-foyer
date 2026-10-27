from __future__ import annotations

from homeassistant.components.lock import LockEntity
from homeassistant.const import ATTR_CODE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import CONF_PIN, FoyerConfigEntry, FoyerEntity, add_devices
from .api import PinRequired, bool_wrapper, str_wrapper


async def async_setup_entry(
    hass: HomeAssistant, entry: FoyerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    add_devices(entry, async_add_entities, Platform.LOCK, FoyerLock)


class FoyerLock(FoyerEntity, LockEntity):
    @property
    def is_locked(self) -> bool | None:
        return self.state_data.locked

    @property
    def is_jammed(self) -> bool | None:
        return self.state_data.jammed

    async def _set(self, locked: bool, pin: str | None) -> None:
        try:
            await self._apply(
                self.coordinator.client.update(
                    self.device, "lockUnlock", [("isLocked", bool_wrapper(locked))]
                )
            )
        except HomeAssistantError as err:
            if not isinstance(err.__cause__, PinRequired):
                raise
            if not pin:
                raise HomeAssistantError(
                    f"{self.device.name} needs a PIN: pass a code or set one in integration options."
                ) from err
            await self._update(
                "lockUnlock", [("isLocked", bool_wrapper(locked)), ("pin", str_wrapper(pin))]
            )

    async def async_lock(self, **kwargs) -> None:
        await self._set(True, kwargs.get(ATTR_CODE) or self._pin)

    async def async_unlock(self, **kwargs) -> None:
        await self._set(False, kwargs.get(ATTR_CODE) or self._pin)

    @property
    def _pin(self) -> str | None:
        return self.coordinator.config_entry.options.get(CONF_PIN) or None
