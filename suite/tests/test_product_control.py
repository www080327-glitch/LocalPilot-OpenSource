"""Deterministic safety controls. Provider responses here are scripted."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from localpilot_suite.product_control import dispatch

class Admin:
    calls=[]
    def capabilities(self):return {'settings_fields':['max_context_window','ttl_seconds']}
    def require(self,*args):pass
    def request(self,path,body=None,method=None):
        self.calls.append((path,body,method))
        if path=='/admin/api/models':return {'models':[{'id':'fixture','loaded':True,'model_context_length':8192}]}
        if path.startswith('/admin/api/hf/model-info'):return {'size':0}
        return {}

class ProductControlTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name);Admin.calls=[]
    def tearDown(self):self.tmp.cleanup()
    def dispatch(self,op,args):return dispatch(self.home,{'version':1,'operation':op,'args':args})
    def test_provider_parameter_cannot_enable_remote_code(self):
        with patch('localpilot_suite.product_control.OmlxAdmin',Admin):
            with self.assertRaises(ValueError):self.dispatch('settings',{'model':'fixture','settings':{'trust_remote_code':True},'confirmed':True})
        self.assertEqual(Admin.calls,[])
    def test_unknown_download_size_cannot_create_a_job(self):
        with patch('localpilot_suite.product_control.OmlxAdmin',Admin):
            with self.assertRaises(ValueError):self.dispatch('download',{'repo_id':'fixture/model','confirmed':True})
        self.assertFalse(any(p=='/admin/api/hf/download' for p,_,_ in Admin.calls))
    def test_delete_requires_exact_name_and_unloaded_state(self):
        with patch('localpilot_suite.product_control.OmlxAdmin',Admin):
            for typed in ['wrong','fixture']:
                with self.assertRaises(ValueError):self.dispatch('delete',{'model':'fixture','typed_name':typed,'confirmed':True})
        self.assertFalse(any(m=='DELETE' for _,_,m in Admin.calls))
    def test_native_context_limit_is_enforced(self):
        with patch('localpilot_suite.product_control.OmlxAdmin',Admin):
            with self.assertRaises(ValueError):self.dispatch('settings',{'model':'fixture','settings':{'max_context_window':16384},'confirmed':True})
        self.assertFalse(any(m=='PUT' for _,_,m in Admin.calls))
    def test_preferences_are_stored_without_claiming_cache_activation(self):
        out=self.dispatch('preferences',{'model':'fixture','value':{'favorite':True,'cache_prefix':True}})
        self.assertTrue(out['models']['fixture']['cache_prefix']);self.assertIn('preference_only',out['cache_effect'])
        self.assertEqual(self.dispatch('preferences',{})['models'],out['models'])
