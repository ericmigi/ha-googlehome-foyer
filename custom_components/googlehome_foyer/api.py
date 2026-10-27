"""Google Home app private API (foyer-pa), ported from coredevices/pebble-plugins googlehome.

Auth: gpsoauth turns the EmbeddedSetup `oauth_token` cookie into a long-lived master token, and
the master token into short-lived foyer bearers. foyer-pa speaks positional JSON arrays where
protobuf field numbers map to array indices. Scalar wrappers put the value at a type-specific
index: number at 1, string at 2, bool at 3.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import aiohttp

AUTH_URL = "https://android.clients.google.com/auth"
PLACEHOLDER_EMAIL = "owner@example.com"
PLAY_SERVICES_VERSION = "240913000"
GMS_CLIENT_SIG = "38918a453d07199354f8b19af05ec6562ced5788"

FOYER_BASE = "https://googlehomefoyer-pa.clients6.google.com/$rpc/google.internal.home.foyer.v1."
FOYER_APP = "com.google.android.apps.chromecast.app"
FOYER_CLIENT_SIG = "24bb24c05e47e0aefa68a58a766179d9b613a600"
SCOPES = [
    "oauth2:https://www.googleapis.com/auth/homegraph",
    "oauth2:https://www.google.com/accounts/OAuthLogin",
]

MEDIA_STATES = {"play": "playing", "pause": "paused", "stop": "stopped"}


_SECRETS = [
    (re.compile(r"aas_et/[\w./+=-]+"), "<redacted>"),
    (re.compile(r"oauth2_4/[\w./+=-]+"), "<redacted>"),
    (re.compile(r"ya29\.[\w./+=-]+"), "<redacted>"),
    (re.compile(r"bearer\s+[\w./+=-]+", re.I), "Bearer <redacted>"),
    (
        re.compile(r"(EncryptedPasswd|oauth_token|Token|ACCESS_TOKEN|Authorization|Auth)=[^&\s\"]+", re.I),
        r"\1=<redacted>",
    ),
]


def redact(text: str) -> str:
    for pattern, repl in _SECRETS:
        text = pattern.sub(repl, text)
    return text


class FoyerError(Exception):
    """Any foyer or gpsoauth failure. Messages are redacted since they reach logs and the UI."""

    def __init__(self, message: str) -> None:
        super().__init__(redact(message))


class FoyerAuthError(FoyerError):
    """Credentials rejected; the user has to sign in again."""


class PinRequired(FoyerError):
    """The device asked for a PIN challenge (unlock)."""


# --- positional-array helpers ------------------------------------------------------------------


def _at(a: Any, i: int) -> Any:
    return a[i] if isinstance(a, list) and 0 <= i < len(a) else None


def _arr(a: Any, i: int) -> list | None:
    v = _at(a, i)
    return v if isinstance(v, list) else None


def _str(a: Any, i: int) -> str | None:
    v = _at(a, i)
    return v if isinstance(v, str) else None


def _num(a: Any, i: int) -> float | None:
    v = _at(a, i)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _bool(a: Any, i: int) -> bool:
    v = _at(a, i)
    return v if isinstance(v, bool) else v == 1


def _fields(body: Any) -> dict[str, Any]:
    """`[[fieldName, wrapper], ...]` -> {fieldName: wrapper}."""
    out: dict[str, Any] = {}
    for f in body if isinstance(body, list) else []:
        name = _str(f, 0)
        if name is not None:
            out[name] = _arr(f, 1)
    return out


def js_round(x: float) -> int:
    """JS Math.round (halves up), not Python's round-half-to-even."""
    return math.floor(x + 0.5)


def num_wrapper(n: float) -> list:
    return [None, n]


def str_wrapper(s: str) -> list:
    return [None, None, s]


def bool_wrapper(b: bool) -> list:
    return [None, None, None, 1 if b else 0]


# --- model -------------------------------------------------------------------------------------


@dataclass
class Device:
    id: str
    home_id: str
    name: str
    type: str
    traits: list[str]
    room: str | None
    agent_id: str
    partner_id: str
    caps: set[str] = field(default_factory=set)


@dataclass
class DeviceState:
    id: str
    online: bool | None = None  # None: response carried no deviceStatus
    on: bool | None = None
    brightness: float | None = None
    color_temp_k: float | None = None
    volume: float | None = None
    muted: bool | None = None
    locked: bool | None = None
    jammed: bool | None = None
    mode: str | None = None
    setpoint_c: float | None = None
    ambient_c: float | None = None
    unit: str | None = None


@dataclass
class Automation:
    id: str
    home_id: str
    name: str
    manually_runnable: bool


_CAPS = {
    "onoff": {"on_off"},
    "brightness": {"brightness"},
    "colorsetting": {"color_temperature"},
    "volume": {"volume"},
    "lockunlock": {"lock"},
    "temperaturesetting": {"thermostat"},
    "temperaturecontrol": {"thermostat"},
    "transportcontrol": {"media"},
    "mediastate": {"media"},
}


def derive_caps(traits: list[str]) -> set[str]:
    caps: set[str] = set()
    for t in traits:
        caps |= _CAPS.get(t.rsplit(".", 1)[-1].lower(), set())
    return caps


# --- codec -------------------------------------------------------------------------------------


def parse_home_graph(js: Any) -> tuple[list[tuple[str, str]], list[Device]]:
    homes: list[tuple[str, str]] = []
    devices: list[Device] = []
    for home in _arr(js, 1) or []:
        home_id = _str(home, 0)
        if home_id is None:
            continue
        homes.append((home_id, _str(home, 1) or ""))
        room_of: dict[str, str] = {}
        for room in _arr(home, 5) or []:
            for member in _arr(room, 4) or []:
                dev_id = _str(_arr(member, 0), 0)
                if dev_id:
                    room_of[dev_id] = _str(room, 2) or ""
        for rec in _arr(home, 6) or []:
            key = _arr(rec, 0)
            dev_id = _str(key, 0)
            if dev_id is None:
                continue
            agent = _arr(key, 1)
            traits = [t for t in _arr(rec, 6) or [] if isinstance(t, str)]
            # [20] is the user-assigned type; it overrides the hardware type [5].
            dev_type = _str(_arr(rec, 20), 0) or _str(rec, 5) or ""
            devices.append(
                Device(
                    id=dev_id,
                    home_id=home_id,
                    name=_str(rec, 3) or "",
                    type=dev_type,
                    traits=traits,
                    room=room_of.get(dev_id),
                    agent_id=_str(agent, 0) or "",
                    partner_id=_str(agent, 1) or "",
                    caps=derive_caps(traits),
                )
            )
    return homes, devices


def parse_traits(js: Any) -> list[DeviceState]:
    out: list[DeviceState] = []
    for r in _arr(js, 0) or []:
        dev_id = _str(_arr(r, 0), 0)
        if dev_id is None:
            continue
        s = DeviceState(id=dev_id)
        for e in _arr(r, 1) or []:
            f = _fields(_arr(e, 1))
            match _str(e, 0):
                case "deviceStatus":
                    if "online" in f:
                        s.online = _bool(f["online"], 3)
                case "onOff":
                    if "onOff" in f:
                        s.on = _bool(f["onOff"], 3)
                case "brightness":
                    s.brightness = _num(f.get("brightness"), 1)
                case "color":
                    s.color_temp_k = _num(f.get("colorTemperature"), 1)
                case "volume":
                    s.volume = _num(f.get("currentVolume"), 1)
                    if "isMuted" in f:
                        s.muted = _bool(f["isMuted"], 3)
                case "lockUnlock":
                    if "isLocked" in f:
                        s.locked = _bool(f["isLocked"], 3)
                    if "isJammed" in f:
                        s.jammed = _bool(f["isJammed"], 3)
                case "temperatureSetting":
                    s.mode = _str(f.get("mode"), 2)
                    s.setpoint_c = _num(f.get("thermostatTemperatureSetpointC"), 1)
                    s.ambient_c = _num(f.get("ambientAirTemperatureC"), 1)
                    # temperatureUnit lives in the params block (index 2), one array deeper.
                    s.unit = _str(_fields(_arr(_arr(e, 2), 0)).get("temperatureUnit"), 2)
        out.append(s)
    return out


def parse_challenge(js: Any) -> str | None:
    for r in _arr(js, 0) or []:
        for e in _arr(r, 1) or []:
            if _str(e, 0) == "deviceStatus":
                v = _str(_fields(_arr(e, 1)).get("challenge"), 2)
                if v is not None:
                    return v
    return None


def parse_automations(js: Any, home_id: str) -> list[Automation]:
    out = []
    for rec in _arr(js, 0) or []:
        auto_id, name = _str(rec, 0), _str(rec, 3)
        if auto_id and name:
            out.append(Automation(auto_id, home_id, name, _num(rec, 2) == 1))
    return out


def build_update(dev: Device, trait: str, fields: list[tuple[str, list]]) -> list:
    return [[[[dev.id, [dev.agent_id, dev.partner_id]], [[trait, [list(f) for f in fields]]]]]]


def build_traits_request(ids: list[str]) -> list:
    return [[[i] for i in ids]]


# --- gpsoauth ----------------------------------------------------------------------------------


def _common_form(android_id: str) -> dict[str, str]:
    return {
        "accountType": "HOSTED_OR_GOOGLE",
        "Email": PLACEHOLDER_EMAIL,
        "has_permission": "1",
        "source": "android",
        "androidId": android_id,
        "device_country": "us",
        "operatorCountry": "us",
        "lang": "en",
        "sdk_version": "17",
        "google_play_services_version": PLAY_SERVICES_VERSION,
    }


def parse_auth_response(body: str) -> dict[str, str]:
    out = {}
    for line in body.splitlines():
        k, sep, v = line.strip().partition("=")
        if sep:
            out[k] = v
    return out


async def _auth_post(session: aiohttp.ClientSession, form: dict[str, str]) -> dict[str, str]:
    """POST to gpsoauth. Server-side failures raise FoyerError; a parsed reply is returned for
    2xx and for 4xx, where Google reports rejected credentials (e.g. Error=BadAuthentication)."""
    body = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in form.items())
    try:
        async with session.post(
            AUTH_URL,
            data=body,
            headers={
                "User-Agent": "GoogleAuth/1.4",
                "Accept-Encoding": "identity",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        ) as resp:
            status, text = resp.status, await resp.text()
    except aiohttp.ClientError as err:
        raise FoyerError(f"Google auth request failed: {err}") from err
    if status == 429 or status >= 500:
        raise FoyerError(f"Google auth: HTTP {status}")
    return parse_auth_response(text)


async def exchange_oauth_token(
    session: aiohttp.ClientSession, oauth_token: str, android_id: str
) -> tuple[str, str | None]:
    """EmbeddedSetup oauth_token cookie -> (master token, account email)."""
    form = _common_form(android_id) | {
        "add_account": "1",
        "ACCESS_TOKEN": "1",
        "Token": oauth_token,
        "service": "ac2dm",
        "client_sig": GMS_CLIENT_SIG,
        "callerSig": GMS_CLIENT_SIG,
        "droidguard_results": "dummy123",
    }
    parsed = await _auth_post(session, form)
    if "Token" not in parsed:
        raise FoyerAuthError(f"oauth_token exchange failed: {parsed.get('Error', 'no Token')}")
    return parsed["Token"], parsed.get("Email") or None


# --- client ------------------------------------------------------------------------------------


class FoyerClient:
    """foyer-pa RPC client; mints and caches the bearer, retries once on 401/403."""

    def __init__(self, session: aiohttp.ClientSession, master_token: str, android_id: str) -> None:
        self._session = session
        self._master = master_token
        self._android_id = android_id
        self._bearer: str | None = None
        self._expires = 0.0
        self._scope = 0

    async def _mint(self) -> str:
        last = "no scopes"
        for offset in range(len(SCOPES)):
            i = (self._scope + offset) % len(SCOPES)
            form = _common_form(self._android_id) | {
                "EncryptedPasswd": self._master,  # carries the master token verbatim
                "service": SCOPES[i],
                "app": FOYER_APP,
                "client_sig": FOYER_CLIENT_SIG,
            }
            parsed = await _auth_post(self._session, form)
            if "Auth" in parsed:
                now = time.time()
                cap = now + 55 * 60
                expiry = float(parsed["Expiry"]) if parsed.get("Expiry", "").isdigit() else cap
                self._scope, self._bearer = i, parsed["Auth"]
                self._expires = min(expiry if expiry > now else cap, cap) - 60
                return self._bearer
            last = parsed.get("Error", "unknown")
        raise FoyerAuthError(f"getAuthToken failed: {last}")

    async def _token(self) -> str:
        if self._bearer and time.time() < self._expires:
            return self._bearer
        return await self._mint()

    async def rpc(self, service: str, method: str, body: list) -> Any:
        url = f"{FOYER_BASE}{service}/{method}"
        for attempt in range(2):
            try:
                async with self._session.post(
                    url,
                    data=json.dumps(body),
                    headers={
                        "Authorization": f"Bearer {await self._token()}",
                        "X-User-Agent": "grpc-web-javascript/0.1",
                        "Content-Type": "application/json+protobuf",
                    },
                ) as resp:
                    status, text = resp.status, await resp.text()
            except aiohttp.ClientError as err:
                raise FoyerError(f"foyer {method} request failed: {err}") from err
            if status in (401, 403) and attempt == 0:
                self._bearer, self._expires = None, 0
                self._scope = (self._scope + 1) % len(SCOPES)
                continue
            if status in (401, 403):
                raise FoyerAuthError(f"foyer {method}: HTTP {status}")
            if not 200 <= status < 300:
                raise FoyerError(f"foyer {method}: HTTP {status}: {text[:200]}")
            text = text.lstrip()
            if text.startswith(")]}'"):
                text = text[4:].lstrip("\r\n")
            return json.loads(text)
        raise FoyerError("unreachable")

    async def home_graph(self) -> tuple[list[tuple[str, str]], list[Device]]:
        return parse_home_graph(await self.rpc("StructuresService", "GetHomeGraph", []))

    async def traits(self, ids: list[str]) -> list[DeviceState]:
        if not ids:
            return []
        return parse_traits(
            await self.rpc("HomeControlService", "GetTraits", build_traits_request(ids))
        )

    async def update(self, dev: Device, trait: str, fields: list[tuple[str, list]]) -> DeviceState | None:
        resp = await self.rpc("HomeControlService", "UpdateTraits", build_update(dev, trait, fields))
        if trait == "lockUnlock" and parse_challenge(resp) is not None:
            raise PinRequired(f"{dev.name} requires a PIN")
        return next((s for s in parse_traits(resp) if s.id == dev.id), None)

    async def set_thermostat(
        self, dev: Device, setpoint_c: float | None, mode: str | None
    ) -> DeviceState | None:
        # Nest wants `mode` alongside the setpoint, in the device's DISPLAY unit; read both fresh.
        current = next((s for s in await self.traits([dev.id]) if s.id == dev.id), None)
        unit = (current.unit if current and current.unit else "F").upper()
        fields: list[tuple[str, list]] = [
            ("mode", str_wrapper(mode or (current.mode if current else None) or "heat"))
        ]
        if setpoint_c is not None:
            display = (
                js_round(setpoint_c * 9 / 5 + 32) if unit == "F" else js_round(setpoint_c * 2) / 2
            )
            fields.append(("thermostatTemperatureSetpoint", num_wrapper(display)))
        return await self.update(dev, "temperatureSetting", fields)

    async def automations(self, home_id: str) -> list[Automation]:
        return parse_automations(
            await self.rpc("AutomationService", "ListAutomations", [home_id]), home_id
        )

    async def run_automation(self, auto: Automation) -> bool:
        resp = await self.rpc(
            "AutomationService", "ExecuteAutomation", [auto.home_id, auto.id, None, 2]
        )
        return isinstance(resp, list) and len(resp) > 0 and str(resp[0]) == "1"
