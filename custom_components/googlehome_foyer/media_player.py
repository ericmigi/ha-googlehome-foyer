from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FoyerConfigEntry, FoyerEntity, add_devices
from .api import MEDIA_STATES, bool_wrapper, num_wrapper, str_wrapper


async def async_setup_entry(
    hass: HomeAssistant, entry: FoyerConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    add_devices(entry, async_add_entities, Platform.MEDIA_PLAYER, FoyerMediaPlayer)


class FoyerMediaPlayer(FoyerEntity, MediaPlayerEntity):
    """Speakers, displays and TVs. Playback state isn't readable, only commandable."""

    def __init__(self, coordinator, device) -> None:
        super().__init__(coordinator, device)
        f = MediaPlayerEntityFeature(0)
        if "volume" in device.caps:
            f |= MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_MUTE
        if "media" in device.caps:
            f |= MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.PAUSE | MediaPlayerEntityFeature.STOP
        if "on_off" in device.caps:
            f |= MediaPlayerEntityFeature.TURN_ON | MediaPlayerEntityFeature.TURN_OFF
        self._attr_supported_features = f

    @property
    def state(self) -> MediaPlayerState:
        return MediaPlayerState.OFF if self.state_data.on is False else MediaPlayerState.ON

    @property
    def volume_level(self) -> float | None:
        v = self.state_data.volume
        return None if v is None else v / 100

    @property
    def is_volume_muted(self) -> bool | None:
        return self.state_data.muted

    async def async_set_volume_level(self, volume: float) -> None:
        await self._update("volume", [("currentVolume", num_wrapper(round(volume * 100)))])

    async def async_mute_volume(self, mute: bool) -> None:
        await self._update("volume", [("isMuted", bool_wrapper(mute))])

    async def _media(self, command: str) -> None:
        await self._update("mediaState", [("playbackState", str_wrapper(MEDIA_STATES[command]))])

    async def async_media_play(self) -> None:
        await self._media("play")

    async def async_media_pause(self) -> None:
        await self._media("pause")

    async def async_media_stop(self) -> None:
        await self._media("stop")

    async def async_turn_on(self) -> None:
        await self._update("onOff", [("onOff", bool_wrapper(True))])

    async def async_turn_off(self) -> None:
        await self._update("onOff", [("onOff", bool_wrapper(False))])
