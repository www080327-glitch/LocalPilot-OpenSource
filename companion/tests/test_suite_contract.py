"""Consumer-owned version negotiation and no-inference-on-battery controls."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from companion.config import Config
from companion.escalation.compatibility import REQUIRED, incompatibility
from companion.model.backend import ModelManager


class SuiteContractTests(unittest.TestCase):
    def test_public_contract_accepts_compatible_upgrade_not_version_string(self):
        self.assertIsNone(incompatibility({'version':'99.0','compatibility':{'agent_service_api':'1.0','companion_client_contract':'1.0','capabilities':sorted(REQUIRED)}}))
        self.assertIsNone(incompatibility({'compatibility':{'agent_service_api':'1.1','companion_client_contract':'1.1','capabilities':sorted(REQUIRED)}}))
        self.assertIsNotNone(incompatibility({'compatibility':{'agent_service_api':'1.0','companion_client_contract':'1.0','capabilities':sorted(REQUIRED),'minimum_companion':'0.5.7'}}))
        self.assertIsNone(incompatibility({'version':'4.9.1rc2'}))
        self.assertIsNotNone(incompatibility({'version':'4.9.2rc1'}))
        self.assertIsNotNone(incompatibility({'compatibility':{'agent_service_api':'2.0'}}))
        self.assertIsNotNone(incompatibility({'compatibility':{'agent_service_api':'1.0','companion_client_contract':'1.0','capabilities':[]}}))

    def test_battery_and_unknown_power_prevent_http_and_worker_spawn(self):
        for battery in [None,SimpleNamespace(power_plugged=False)]:
            for backend in ['mlx','local-http']:
                m=ModelManager(Config(backend=backend,low_power_policy='off',model_path='/not-used'))
                with patch('psutil.sensors_battery',return_value=battery), patch('subprocess.Popen',side_effect=AssertionError('worker must not start')):
                    result=m.complete([{'role':'user','content':'private'}])
                self.assertEqual(result['error_stage'],'power_policy');self.assertEqual(m.inferences,0)

    def test_operator_disable_wins_even_on_ac_and_battery_opt_in(self):
        m=ModelManager(Config(backend='mlx',allow_local_on_battery=True,low_power_policy='off'))
        with patch.dict('os.environ',LOCALPILOT_DISABLE_LOCAL_MODELS='1'),patch('subprocess.Popen',side_effect=AssertionError):
            result=m.complete([])
        self.assertEqual(result['error_stage'],'power_policy');self.assertEqual(m.inferences,0)


class QuestionOnlyWireTests(unittest.TestCase):
    def test_cloud_wire_is_exact_original_question_without_local_metadata(self):
        from unittest.mock import Mock
        from companion.escalation.localpilot import LocalPilotProvider
        from companion.escalation.provider import EscalationRequest
        p=LocalPilotProvider(Config(localpilot_host_local_only=False,localpilot_allow_cloud=True))
        p._request=Mock(return_value={"id":"resp_fixture","session_id":"sess_fixture","status":"queued"})
        q=EscalationRequest("What is 17 plus 25?","LOCAL-INTENT-CANARY","LOCAL-REASON-CANARY",[],[],[],{ "classification":"PUBLIC","local_only":False,"omitted_local_records":3},"LOCAL-SUMMARY-CANARY")
        p.submit(q,approved=True,cloud_approved=True,submission_id="wire-original")
        self.assertEqual(p._request.call_args.args[1]["input"],q.user_request)
