"""Managed cached model guard unit tests; no MLX process/download."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import time

from localpilot_service import cached_omlx as module


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.snapshot=self.root/module.REVISION;self.snapshot.mkdir()
        (self.snapshot/'config.json').write_text('{}')
        (self.snapshot/'weights.safetensors').write_bytes(b'fixture')
        with patch.object(module,'SNAPSHOT',self.snapshot),patch.object(module,'BINARY','/usr/bin/true'),patch.object(module.sys,'platform','darwin'):
            self.host=module.CachedOmlxHost({'snapshot':str(self.snapshot)},self.root/'private')
        self.host.close=Mock()
        self.battery=patch('psutil.sensors_battery',return_value=SimpleNamespace(power_plugged=True));self.battery.start()

    def tearDown(self):self.battery.stop();self.tmp.cleanup()

    def test_battery_needs_explicit_scoped_grant(self):
        with patch('psutil.sensors_battery',return_value=SimpleNamespace(power_plugged=False)):
            with self.assertRaisesRegex(Exception,'battery_confirmation_required'):
                with self.host.lease('one',client_subject='companion',control_ticket='t'*32):pass
        self.assertEqual(self.host.active,0)

    def test_battery_permission_is_not_memory_override(self):
        self.host._ensure=Mock()
        grant={'client_subject':'companion','expires_at':time.time()+60,'allow_on_battery':True}
        with patch('psutil.sensors_battery',return_value=SimpleNamespace(power_plugged=False)):
            with self.host.lease('one',grant,'companion',control_ticket='t'*32):
                self.assertEqual(self.host.active,1)
                self.assertFalse(self.host._ensure.call_args.kwargs['memory_override'])
        self.host.close.assert_called_once()
        self.assertEqual(self.host.active,0)

    def test_low_memory_wall_and_critical_floor(self):
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=10*1024**3)):
            with self.assertRaisesRegex(Exception,'resource_budget_exceeded'):self.host._ensure()
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=2*1024**3)):
            with self.assertRaisesRegex(Exception,'resource_budget_exceeded'):self.host._ensure(memory_override=True)

    def test_scope_expiry_and_ui_heartbeat(self):
        self.host._ensure=Mock()
        grant={'client_subject':'other','expires_at':time.time()+60,'allow_memory_override':True}
        with self.host.lease('one',grant,'companion',control_ticket='t'*32):
            self.assertFalse(self.host._ensure.call_args.kwargs['memory_override'])
            old=self.host.gui_deadlines['one'];self.host.heartbeat('one','wrong')
            self.assertEqual(self.host.gui_deadlines['one'],old)
            self.host.heartbeat('one','t'*32);self.assertGreaterEqual(self.host.gui_deadlines['one'],old)
        self.assertEqual(self.host.control_tickets,{})

    def test_no_control_ticket_no_large_model(self):
        self.host._ensure=Mock()
        with self.assertRaisesRegex(Exception,'control_surface_required'):
            with self.host.lease('one'):pass
        self.host._ensure.assert_not_called()

    def test_exception_releases_lease(self):
        self.host._ensure=Mock(side_effect=RuntimeError('fixture failure'))
        with self.assertRaises(RuntimeError):
            with self.host.lease('one',control_ticket='t'*32):pass
        self.host.close.assert_called_once();self.assertEqual(self.host.active_tasks,set())
