# Google Home (Foyer) for Home Assistant

Control the devices and automations in your **Google Home app** from Home Assistant — including
third-party devices that are only linked through Google Home (Wyze, TP-Link, Hue, smart plugs,
locks, etc.), not just Google's own hardware.

> **Unofficial.** This uses the Google Home app's private API (`googlehomefoyer-pa`), reverse
> engineered. It is not the Google Home APIs for developers and is not endorsed by Google. It can
> break whenever Google changes that API.

## What you get

Every device in your Google Home homes becomes one Home Assistant entity, picked by what it can do:

| Google Home device | HA entity | Supports |
|---|---|---|
| Thermostat | `climate` | heat / cool / heat-cool / off, setpoint, eco (as a preset), current temperature |
| Smart lock | `lock` | lock, unlock (PIN-protected locks use the PIN from options or the code you pass) |
| Speaker, display, TV | `media_player` | volume, mute, play / pause / stop, on / off |
| Light | `light` | on / off, brightness, color temperature |
| Anything else with on / off | `switch` | on / off |
| Manually-runnable household automation | `button` | press to run it |

Rooms from Google Home are used as suggested areas. State is polled every 30 seconds and the device
list every 10 minutes; devices and automations you add in Google Home show up automatically.

Not supported (yet): RGB color, heat-cool range setpoints, reading media playback state, adding or
deleting devices / automations.

## Install

**HACS (recommended):** HACS → ⋮ → Custom repositories → add this repository's URL with category
*Integration* → download **Google Home (Foyer)** → restart Home Assistant.

**Manual:** copy `custom_components/googlehome_foyer` into your Home Assistant `config/custom_components/`
folder and restart Home Assistant.

No extra Python packages are needed.

## Set up

The integration signs in the same way the Google Home Android app does. You hand it a one-time
sign-in token, which it exchanges for a long-lived master token.

1. On a desktop browser, open <https://accounts.google.com/EmbeddedSetup> and sign in with the
   Google account that owns your home. When it finishes the page may hang or go blank; that's
   expected.
2. Open developer tools → **Application** (Chrome/Edge) or **Storage** (Firefox) → **Cookies** →
   `https://accounts.google.com`, and copy the value of the **`oauth_token`** cookie (starts with
   `oauth2_4/`).
3. In Home Assistant go to **Settings → Devices & services → Add integration → Google Home (Foyer)**
   and paste the cookie. Do this within a few minutes: the cookie is single-use and expires quickly.
   If Google doesn't return your account email, the form asks for it; your token is kept, just add
   the email and submit again.

Already have a master token (`aas_et/…`) from another tool? Paste it in the master-token field
instead, together with your account email.

**Lock PIN (optional):** if you have PIN-protected locks, open the integration → **Configure** and
save the PIN. Leaving the field blank keeps the saved PIN; tick *Remove saved PIN* to clear it.

If Google later rejects the token, Home Assistant asks you to re-authenticate; repeat the steps above
with the same account.

## Security

The master token gives broad access to your Google account, roughly like a password. Home Assistant
stores it in its config entry on disk (`.storage/core.config_entries`). Protect your Home Assistant
host and backups accordingly, and remove the integration to stop using it (you can also revoke access
from your Google account's security settings). Tokens are redacted from error messages and logs.

## Notes

- If you also use the official Nest or Google Cast integrations, the same thermostat or speakers will
  appear twice. Disable whichever copy you don't want.
- Commands go through Google's cloud, so expect the same latency as the Google Home app.

## Development

`custom_components/googlehome_foyer/api.py` holds the protocol: gpsoauth sign-in, bearer minting,
and the positional `application/json+protobuf` codec. The codec test runs without Home Assistant:

```bash
python3 tests/test_api.py
```

Protocol details are ported from the Google Home plugin in
[coredevices/pebble-plugins](https://github.com/coredevices/pebble-plugins/tree/main/googlehome).

## License

MIT, see [LICENSE](LICENSE).
