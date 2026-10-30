"""A request slot has one release owner even if thread startup is interrupted."""
import threading
import unittest
from unittest.mock import patch
from localpilot_api.server import APIServer
from localpilot_service.server import ServiceServer

class SignalAdmissionTests(unittest.TestCase):
    def server(self):
        value=object.__new__(ServiceServer);value.handler_slots=threading.BoundedSemaphore(1)
        value.handler_leases=set();value.handler_lease_lock=threading.Lock();return value
    def test_worker_release_then_interrupted_start_does_not_release_twice(self):
        server=self.server();request=object()
        def interrupted(*args):
            server.release_handler(request)
            raise KeyboardInterrupt
        with patch.object(APIServer,'process_request',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):server.process_request(request,('127.0.0.1',0))
        self.assertTrue(server.handler_slots.acquire(blocking=False));self.assertFalse(server.handler_slots.acquire(blocking=False))
        self.assertFalse(server.handler_leases)
    def test_failed_start_before_worker_restores_one_slot(self):
        server=self.server();request=object()
        with patch.object(APIServer,'process_request',side_effect=RuntimeError('thread start failed')):
            with self.assertRaises(RuntimeError):server.process_request(request,('127.0.0.1',0))
        self.assertTrue(server.handler_slots.acquire(blocking=False));self.assertFalse(server.handler_slots.acquire(blocking=False))
