"""Codec checks against the live-captured wire shapes.

Run: python3 tests/test_api.py  (needs aiohttp importable)
"""

import importlib.util
import json
import pathlib
import sys

_p = pathlib.Path(__file__).parent.parent / "custom_components/googlehome_foyer/api.py"
_spec = importlib.util.spec_from_file_location("api", _p)
api = sys.modules["api"] = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api)

DEV = api.Device("22222222-2222-4222-8222-222222222222", "h", "Outside", "", [], None, "acme-partner", "AA11BB22CC33DD44EE55")
P = '[[[["22222222-2222-4222-8222-222222222222",["acme-partner","AA11BB22CC33DD44EE55"]],'


def s(x):
    return json.dumps(x, separators=(",", ":"))


def test_builders():
    assert s(api.build_update(DEV, "onOff", [("onOff", api.bool_wrapper(True))])) == P + '[["onOff",[["onOff",[null,null,null,1]]]]]]]]'
    assert s(api.build_update(DEV, "brightness", [("brightness", api.num_wrapper(42))])) == P + '[["brightness",[["brightness",[null,42]]]]]]]]'
    assert s(api.build_update(DEV, "lockUnlock", [("isLocked", api.bool_wrapper(False)), ("pin", api.str_wrapper("1234"))])) == P + '[["lockUnlock",[["isLocked",[null,null,null,0]],["pin",[null,null,"1234"]]]]]]]]'
    assert s(api.build_traits_request([DEV.id])) == '[[["22222222-2222-4222-8222-222222222222"]]]'


def test_parse_traits():
    payload = (
        '[[[["dev"],['
        '["deviceStatus",[["online",[null,null,null,1]]]],'
        '["onOff",[["onOff",[null,null,null,1]]]],'
        '["brightness",[["brightness",[null,42]]]],'
        '["color",[["colorTemperature",[null,4000]]]],'
        '["volume",[["currentVolume",[null,55]],["isMuted",[null,null,null,1]]]],'
        '["lockUnlock",[["isLocked",[null,null,null,1]],["isJammed",[null,null,null,0]]]],'
        '["temperatureSetting",[["mode",[null,null,"heat"]],'
        '["thermostatTemperatureSetpointC",[null,19.5]],["ambientAirTemperatureC",[null,21.0]]],'
        '[[["temperatureUnit",[null,null,"C"]]]]]'
        "]]]]"
    )
    st = api.parse_traits(json.loads(payload))[0]
    assert (st.id, st.online, st.on, st.brightness, st.color_temp_k) == ("dev", True, True, 42, 4000)
    assert (st.volume, st.muted, st.locked, st.jammed) == (55, True, True, False)
    assert (st.mode, st.setpoint_c, st.ambient_c, st.unit) == ("heat", 19.5, 21.0, "C")
    assert api.parse_challenge(json.loads('[[[["dev"],[["deviceStatus",[["challenge",[null,null,"pinNeeded"]]]]]]]]')) == "pinNeeded"


def test_home_graph():
    dev = [None] * 21
    dev[0] = ["d1", ["agent", "p1"]]
    dev[3], dev[5], dev[6] = "Porch", "action.devices.types.OUTLET", ["action.devices.traits.OnOff"]
    dev[20] = ["action.devices.types.LIGHT"]
    room = ["r1", None, "Front", ["OUTDOOR"], [[["d1", ["agent", "p1"]]]]]
    home = ["h1", "Home", None, None, None, [room], [dev]]
    homes, devices = api.parse_home_graph([None, [home]])
    assert homes == [("h1", "Home")]
    d = devices[0]
    assert (d.id, d.home_id, d.name, d.type, d.room, d.agent_id, d.partner_id) == ("d1", "h1", "Porch", "action.devices.types.LIGHT", "Front", "agent", "p1")
    assert d.caps == {"on_off"}


def test_redact_and_round():
    err = api.FoyerError("HTTP 400: Token=aas_et/AbC123== Authorization: Bearer ya29.xyz oauth2_4/qq")
    assert "aas_et" not in str(err) and "ya29" not in str(err) and "oauth2_4" not in str(err), str(err)
    assert (api.js_round(40.5), api.js_round(41.5), api.js_round(-0.5)) == (41, 42, 0)
    assert api.parse_traits(json.loads('[[[["d"],[["onOff",[["onOff",[null,null,null,1]]]]]]]]'))[0].online is None


if __name__ == "__main__":
    test_builders()
    test_parse_traits()
    test_home_graph()
    test_redact_and_round()
    print("ok")
