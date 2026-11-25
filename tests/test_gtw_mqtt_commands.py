"""Unit tests for GTW_Control_Comms/gtw_mqtt_commands.py - E-STOP routing.

Related test-suite cases in GUI_test_suite.xlsx:
    REQ-006 E-STOP              TC-038, TC-039, TC-040, TC-045
    REQ-007 Cutterhead logging  TC-050
    REQ-008 PCAN unavailable    TC-054
Each test lists its cases in a "Related test-suite cases:" line.

emergency_mode() is the single entry point for the Dashboard's mushroom
button and the Control Panel's EMERGENCY STOP / SAFE MODE / CLEAR buttons.
These tests check it reaches the PCAN cutterhead and still tells the H7,
with no network or CAN hardware.
"""
from unittest import mock

import pytest

import GTW_Control_Comms.gtw_mqtt_commands as gtw
import IO_devices.cutterhead_pcan_bridge as cutter_pcan


def take_messages():
    items = []
    while not gtw.msg_queue.empty():
        items.append(gtw.msg_queue.get_nowait())
    return items


def odrive_messages():
    return [text for kind, text in take_messages() if kind == "odrive_status"]


@pytest.fixture(autouse=True)
def empty_msg_queue():
    """msg_queue is a single module-level queue shared by every test."""
    take_messages()
    yield
    take_messages()


@pytest.fixture
def mqtt_client(monkeypatch):
    """Replaces the paho client, so nothing goes on the network. publish()
    reports success, like a connected broker would."""
    client = mock.Mock()
    client.publish.return_value = mock.Mock(rc=gtw.mqtt.MQTT_ERR_SUCCESS)
    monkeypatch.setattr(gtw, "client", client)
    return client


@pytest.fixture
def cutterhead(monkeypatch):
    """Replaces the shared CutterheadPCAN that get_cutterhead_pcan()
    returns, however gtw_mqtt_commands ends up importing it."""
    fake = mock.create_autospec(cutter_pcan.CutterheadPCAN, instance=True)
    fake.emergency_stop.return_value = True
    monkeypatch.setattr(cutter_pcan, "_cutterhead_pcan", fake)
    return fake


@pytest.mark.parametrize("status", ["EMERGENCY_STOP", "SAFE_MODE"])
def test_stop_commands_emergency_stop_the_cutterhead(status, mqtt_client, cutterhead):
    """Related test-suite cases: TC-038, TC-039, TC-040"""
    gtw.emergency_mode(status)

    cutterhead.emergency_stop.assert_called_once_with()
    cutterhead.clear_emergency.assert_not_called()


def test_clear_releases_the_cutterhead_latch(mqtt_client, cutterhead):
    """Related test-suite cases: TC-045"""
    gtw.emergency_mode("CLEAR EMERGENCY")

    cutterhead.clear_emergency.assert_called_once_with()
    cutterhead.emergency_stop.assert_not_called()


@pytest.mark.parametrize("status", ["EMERGENCY_STOP", "SAFE_MODE", "CLEAR EMERGENCY"])
def test_emergency_commands_still_reach_the_h7(status, mqtt_client, cutterhead):
    """Related test-suite cases: none"""
    gtw.emergency_mode(status)

    mqtt_client.publish.assert_any_call(gtw.TOPIC_EMERGENCY, status)


def test_emergency_stop_reports_success_without_warnings(mqtt_client, cutterhead):
    """Related test-suite cases: TC-050"""
    gtw.emergency_mode("EMERGENCY_STOP")

    messages = odrive_messages()
    assert messages, "the operator must be told the outcome"
    assert not any("FAILED" in m.upper() or "WARNING" in m.upper() for m in messages)


def test_emergency_stop_reports_failure_when_cutterhead_not_stopped(mqtt_client, cutterhead):
    """Related test-suite cases: TC-054"""
    cutterhead.emergency_stop.return_value = False

    gtw.emergency_mode("EMERGENCY_STOP")

    assert any("FAILED" in m.upper() for m in odrive_messages())
