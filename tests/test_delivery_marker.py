"""An opt-in literal delivery line cannot be satisfied by a negated mention."""
from pathlib import Path
import hashlib,tempfile,unittest
from types import SimpleNamespace
from localpilot_service.verification import configured_verifier

class DeliveryMarkerTests(unittest.TestCase):
 def test_line_mode_refuses_negation_quotes_and_substrings(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'result.txt').write_text('correct\n')
   spec={'id':'marker','files':{'result.txt':hashlib.sha256(b'correct\n').hexdigest()},'required_text':'DELIVERED','required_text_mode':'line'}
   verify=configured_verifier(root,spec)
   for text in ['NOT DELIVERED.','I am not claiming `DELIVERED`.','DELIVERED_PARTIALLY','**DELIVERED**']:
    self.assertEqual(verify(root,SimpleNamespace(text=text)).status,'failed')
   self.assertEqual(verify(root,SimpleNamespace(text='File checked.\n\nDELIVERED\n')).status,'passed')
   spec.pop('required_text_mode')
   self.assertEqual(configured_verifier(root,spec)(root,SimpleNamespace(text='substring DELIVERED marker')).status,'passed')
 def test_mode_is_validated(self):
  with tempfile.TemporaryDirectory() as d:
   spec={'id':'marker','files':{'x':'0'*64},'required_text':'DONE','required_text_mode':'regex'}
   with self.assertRaises(ValueError):configured_verifier(Path(d),spec)
