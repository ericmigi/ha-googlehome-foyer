from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FoyerConfigEntry, FoyerCoordinator, add_new
from .api import Automation, FoyerError


async def async_setup_entry(
    hass: HomeAssistant, entry: FoyerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    add_new(
        entry,
        async_add_entities,
        lambda: {k: a for k, a in c.data.automations.items() if a.manually_runnable},
        lambda a: FoyerAutomationButton(c, a),
    )


class FoyerAutomationButton(CoordinatorEntity[FoyerCoordinator], ButtonEntity):
    """Runs a manually-runnable Google Home household automation."""

    _attr_icon = "mdi:robot"

    def __init__(self, coordinator: FoyerCoordinator, auto: Automation) -> None:
        super().__init__(coordinator)
        self._auto_id = auto.id
        self._attr_unique_id = f"automation_{auto.id}"
        self._attr_name = f"Google Home: {auto.name}"

    @property
    def available(self) -> bool:
        return super().available and self._auto_id in self.coordinator.data.automations

    async def async_press(self) -> None:
        auto = self.coordinator.data.automations[self._auto_id]
        try:
            ok = await self.coordinator.client.run_automation(auto)
        except FoyerError as err:
            raise HomeAssistantError(f"Google Home: {err}") from err
        if not ok:
            raise HomeAssistantError(f"Google Home did not start automation {auto.name}.")
