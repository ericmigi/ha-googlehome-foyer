"""Google Home devices and automations via the Google Home app's private API."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import Automation, Device, DeviceState, FoyerAuthError, FoyerClient, FoyerError

_LOGGER = logging.getLogger(__name__)

DOMAIN = "googlehome_foyer"
CONF_MASTER_TOKEN = "master_token"
CONF_ANDROID_ID = "android_id"
CONF_PIN = "lock_pin"
PLATFORMS = [
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.LIGHT,
    Platform.LOCK,
    Platform.MEDIA_PLAYER,
    Platform.SWITCH,
]
# ponytail: fixed poll intervals; foyer has no push channel we know of.
STATE_INTERVAL = timedelta(seconds=30)
GRAPH_INTERVAL = 600


@dataclass
class HomeData:
    devices: dict[str, Device]
    states: dict[str, DeviceState]
    automations: dict[str, Automation]


class FoyerCoordinator(DataUpdateCoordinator[HomeData]):
    """Polls live trait state every 30s and re-reads the home graph every 10 minutes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: FoyerClient) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=STATE_INTERVAL
        )
        self.client = client
        self._graph_at = 0.0

    async def _async_update_data(self) -> HomeData:
        refresh_graph = self.data is None or time.monotonic() - self._graph_at > GRAPH_INTERVAL
        try:
            if refresh_graph:
                homes, devices = await self.client.home_graph()
                automations: dict[str, Automation] = {}
                for home_id, _ in homes:
                    for auto in await self.client.automations(home_id):
                        automations[auto.id] = auto
                by_id = {d.id: d for d in devices}
            else:
                by_id, automations = self.data.devices, self.data.automations
            states = {s.id: s for s in await self.client.traits(list(by_id))}
        except FoyerAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FoyerError as err:
            raise UpdateFailed(str(err)) from err
        if refresh_graph:
            self._graph_at = time.monotonic()  # only once the whole snapshot succeeded
        for s in states.values():
            if s.online is None:
                s.online = False  # polled result without deviceStatus: treat as offline
        return HomeData(by_id, states, automations)


type FoyerConfigEntry = ConfigEntry[FoyerCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: FoyerConfigEntry) -> bool:
    client = FoyerClient(
        async_get_clientsession(hass), entry.data[CONF_MASTER_TOKEN], entry.data[CONF_ANDROID_ID]
    )
    coordinator = FoyerCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FoyerConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def add_devices(
    entry: FoyerConfigEntry,
    async_add_entities: AddEntitiesCallback,
    platform: Platform,
    factory: Callable[[FoyerCoordinator, Device], Entity],
) -> None:
    """Add an entity per device on this platform, now and whenever the graph gains devices."""
    c = entry.runtime_data
    add_new(
        entry,
        async_add_entities,
        lambda: {d.id: d for d in c.data.devices.values() if platform_of(d) == platform},
        lambda d: factory(c, d),
    )


def add_new(
    entry: FoyerConfigEntry,
    async_add_entities: AddEntitiesCallback,
    items: Callable[[], dict[str, Any]],
    factory: Callable[[Any], Entity],
) -> None:
    known: set[str] = set()

    @callback
    def _discover() -> None:
        new = {k: v for k, v in items().items() if k not in known}
        known.update(new)
        if new:
            async_add_entities(factory(v) for v in new.values())

    _discover()
    # Also keeps the coordinator polling when no entities exist yet.
    entry.async_on_unload(entry.runtime_data.async_add_listener(_discover))


def platform_of(d: Device) -> Platform | None:
    """One entity per device, picked by its strongest capability."""
    kind = d.type.rsplit(".", 1)[-1].upper()
    if "thermostat" in d.caps:
        return Platform.CLIMATE
    if "lock" in d.caps:
        return Platform.LOCK
    if "volume" in d.caps or "media" in d.caps:
        return Platform.MEDIA_PLAYER
    if "brightness" in d.caps or "color_temperature" in d.caps or kind == "LIGHT":
        return Platform.LIGHT
    if "on_off" in d.caps:
        return Platform.SWITCH
    return None


class FoyerEntity(CoordinatorEntity[FoyerCoordinator]):
    """A Google Home device; the device's name is the entity name."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: FoyerCoordinator, device: Device) -> None:
        super().__init__(coordinator)
        self._dev_id = device.id
        self._attr_unique_id = device.id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.id)},
            name=device.name,
            model=device.type.rsplit(".", 1)[-1].title() or None,
            manufacturer=device.agent_id or "Google Home",
            suggested_area=device.room or None,
        )

    @property
    def device(self) -> Device:
        return self.coordinator.data.devices[self._dev_id]

    @property
    def state_data(self) -> DeviceState:
        return self.coordinator.data.states.get(self._dev_id) or DeviceState(id=self._dev_id)

    @property
    def available(self) -> bool:
        return (
            super().available
            and self._dev_id in self.coordinator.data.devices
            and self.state_data.online is True
        )

    async def _update(self, trait: str, fields: list[tuple[str, list]]) -> None:
        await self._apply(self.coordinator.client.update(self.device, trait, fields))

    async def _apply(self, call) -> None:
        """Run a control call and fold the echoed state in, else refresh."""
        try:
            new = await call
        except FoyerError as err:
            raise HomeAssistantError(f"Google Home: {err}") from err
        if new is None:
            await self.coordinator.async_request_refresh()
            return
        old = self.coordinator.data.states.get(self._dev_id)
        if old is not None:
            # Echoes carry only the updated trait (often no deviceStatus); keep the rest.
            for key, value in vars(new).items():
                if value is not None:
                    setattr(old, key, value)
        else:
            if new.online is None:
                new.online = True  # it just accepted a command
            self.coordinator.data.states[self._dev_id] = new
        self.coordinator.async_update_listeners()
