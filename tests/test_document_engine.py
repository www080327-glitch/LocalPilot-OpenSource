"""Real parsers/files/SQLite/process limits; model controls are explicitly scripted."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import zipfile

from agent.backends import BackendCapabilities
from agent.hybrid import CloudEgressPolicy, HybridPolicy
from agent.registry import create_default_registry
from agent.session import AgentSession
from localpilot_service.documents import DocumentEngine, DocumentError, Budgets
from localpilot_service.documents.vision import prepare, infer, approve
from tests.document_fixtures import make
from tests.test_runtime_api import Backend, answer, call


class LocalScript(Backend):
    is_local = True


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.inputs=self.root/'inputs';make(self.inputs)
        self.engine = DocumentEngine(self.root/'private')

    def tearDown(self):
        self.engine.close();self.temp.cleanup()

    def add(self,name,subject='user',session='session',process=True):
        aid=self.engine.ingest(subject,session,[str(self.inputs/name)])['files'][0]['id']
        if process:self.engine.process(subject,session,aid)
        return aid

    def nodes(self,aid):
        result=[];cursor=0
        while True:
            r=self.engine.read('user','session',aid,cursor=cursor,limit=50);result+=r['nodes'];cursor=r['next_cursor']
            if not r['has_more']:return result

    def test_real_format_structure_and_independent_anchors(self):
        expectations={'report.pdf':('pdf',{'page':2},'240'),'plan.docx':('docx',{'paragraph':1},'ORBIT Plan'),
                      'budget.xlsx':('xlsx',{'sheet':'ORBIT Budget','cell':'B3'},'240'),
                      'status.pptx':('pptx',{'slide':2},'Approved amount: 240 units'),
                      'data.csv':('csv',{'row':2,'column':1},'ORBIT'), 'data.json':('json',{'line':1},'ORBIT'),
                      'readme.md':('markdown',{'line':1},'ORBIT'),'note.txt':('text',{'line':1},'240')}
        for name,(kind,anchor,quote) in expectations.items():
            with self.subTest(name=name):
                aid=self.add(name);info=self.engine.info('user','session',aid)
                self.assertEqual(info['status'],'complete',info)
                self.assertEqual(info['detected_format'],kind)
                n=next(n for n in self.nodes(aid) if quote in n['text'] and all(n['anchor'].get(k)==v for k,v in anchor.items()))
                self.assertTrue(self.engine.verify('user','session',n['citation'],quote)['verified'])
                self.assertFalse(self.engine.verify('user','session',n['citation'],'invented quotation')['verified'])
                self.assertNotIn(str(self.root),json.dumps(self.nodes(aid)))
        cells=self.nodes(self.add('budget.xlsx'))
        formula=next(n for n in cells if n['anchor'].get('cell')=='B3')['properties']
        self.assertEqual(formula['formula'],'SUM(B1:B2)');self.assertEqual(formula['cached_value'],'240')
        self.assertFalse(formula['formula_evaluated'])
        headings=[n['properties']['level'] for n in self.nodes(self.add('plan.docx')) if n['kind']=='heading']
        self.assertEqual(headings,[1,2])

    def test_multidocument_search_chinese_hybrid_and_source_symbols(self):
        ids=[self.add(n) for n in ['report.pdf','plan.docx','budget.xlsx','status.pptx','readme.md']]
        r=self.engine.search('user','session','240',limit=20)
        self.assertGreaterEqual(len({n['attachment_id'] for n in r['hits']}),4)
        self.assertTrue(self.engine.search('user','session','跨文档')['hits'])
        self.assertEqual(self.engine.search('user','session','ORBIT',mode='hybrid')['vector_kind'],'local_hashed_lexical_not_semantic')
        aid=self.add('project/budget.py')
        self.assertEqual(next(n for n in self.nodes(aid) if n['properties'].get('symbol')=='approved_budget')['anchor']['line'],1)
        refs=self.engine.search('user','session','approved_budget',ids=[aid])['hits']
        self.assertEqual({n['anchor']['line'] for n in refs},{1,5})

    def test_same_file_cache_dedup_and_independent_revocation(self):
        a=self.add('note.txt');b=self.add('note.txt');self.assertEqual(a,b)
        c=self.add('note.txt',session='another')
        self.assertNotEqual(a,c)
        self.assertEqual(len(list(self.engine.blobs.iterdir())),1)
        self.assertTrue(self.engine.process('user','another',c)['cache_hit'])
        cit=self.nodes(a)[1]['citation'];self.engine.revoke('user','session',a)
        for action in [lambda:self.engine.read('user','session',a),lambda:self.engine.verify('user','session',cit,'ORBIT'),lambda:self.engine.process('user','session',a)]:
            with self.assertRaises(DocumentError):action()
        self.assertEqual(self.engine.search('user','session','ORBIT')['hits'],[])
        self.assertTrue(self.engine.read('user','another',c)['nodes'])
        self.assertEqual(self.engine.gc()['collected_blob_bytes'],0)
        self.engine.revoke('user','another',c)
        self.assertGreater(self.engine.gc()['collected_blob_bytes'],0)

    def test_folder_project_import_skips_credentials_and_never_executes(self):
        (self.inputs/'project'/'.env').write_text('private marker')
        (self.inputs/'project'/'danger.sh').write_text('touch SHOULD_NOT_EXIST\n')
        result=self.engine.ingest('user','session',[str(self.inputs/'project')],origin='folder')
        self.assertIn('.env',result['skipped'])
        for f in result['files']:self.engine.process('user','session',f['id'])
        self.assertFalse((self.inputs/'project'/'SHOULD_NOT_EXIST').exists())
        self.assertNotIn(str(self.root),json.dumps(result))
        self.assertGreaterEqual(len(result['files']),3)

    def test_zip_list_and_unsafe_members_bomb_macros_entities(self):
        aid=self.add('project.zip');self.assertEqual(self.engine.info('user','session',aid)['status'],'complete')
        self.assertEqual(len([n for n in self.nodes(aid) if n['kind']=='archive_entry']),2)
        cases={'traversal.zip':[('../escape','bad')], 'absolute.zip':[('/tmp/escape','bad')],
               'backslash.zip':[('..\\escape','bad')], 'bomb.zip':[('repeat','x'*500000)],
               'macro.docx':[('[Content_Types].xml','macroEnabled'),('word/document.xml','<a/>'),('word/vbaProject.bin','data')],
               'entity.docx':[('[Content_Types].xml','<Types/>'),('word/document.xml','<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>')]}
        for name,members in cases.items():
            with self.subTest(name=name):
                with zipfile.ZipFile(self.inputs/name,'w',zipfile.ZIP_DEFLATED) as z:
                    for path,value in members:z.writestr(path,value)
                aid=self.add(name)
                self.assertNotEqual(self.engine.info('user','session',aid)['status'],'complete')
        self.assertFalse((self.root/'escape').exists())

    def test_magic_beats_extension_unsupported_binary_and_json_validation(self):
        (self.inputs/'disguised.txt').write_bytes((self.inputs/'report.pdf').read_bytes())
        aid=self.add('disguised.txt');self.assertEqual(self.engine.info('user','session',aid)['detected_format'],'pdf')
        (self.inputs/'bad.doc').write_bytes(b'\xd0\xcf\x11\xe0binary')
        self.assertEqual(self.engine.info('user','session',self.add('bad.doc'))['status'],'unsupported')
        (self.inputs/'invalid.json').write_text('{invalid}')
        self.assertNotEqual(self.engine.info('user','session',self.add('invalid.json'))['status'],'complete')

    def test_images_multiple_aspect_resolution_orientation_and_pixel_limit(self):
        from PIL import Image
        for name in ['red.png','blue.jpg','green.webp']:
            aid=self.add(name);im=next(n for n in self.nodes(aid) if n['kind']=='image')
            self.assertTrue(im['properties']['original_preserved']);self.assertFalse(im['properties']['visual_understanding'])
        exif=Image.Exif();exif[274]=6
        Image.new('RGB',(40,20),'red').save(self.inputs/'rotated.jpg',exif=exif)
        im=next(n for n in self.nodes(self.add('rotated.jpg')) if n['kind']=='image')['properties']
        self.assertEqual((im['display_width'],im['display_height']),(20,40))
        limited=DocumentEngine(self.root/'limited',replace(Budgets(),pixels=100))
        try:
            aid=limited.ingest('user','session',[str(self.inputs/'red.png')])['files'][0]['id']
            self.assertNotEqual(limited.process('user','session',aid)['status'],'complete')
        finally:limited.close()

    def test_budget_limits_source_and_authorization_isolation(self):
        tiny=DocumentEngine(self.root/'tiny',replace(Budgets(),batch_bytes=10))
        try:
            with self.assertRaises(DocumentError):tiny.ingest('user','s',[str(self.inputs/'note.txt')])
        finally:tiny.close()
        link=self.inputs/'link.txt';link.symlink_to(self.inputs/'note.txt')
        with self.assertRaises(DocumentError):self.engine.ingest('user','s',[str(link)])
        aid=self.add('note.txt')
        with self.assertRaises(DocumentError):self.engine.read('intruder','session',aid)
        with self.assertRaises(DocumentError):self.engine.read('user','different',aid)

    def test_large_attachment_catalog_is_paged_without_a_small_count_cap(self):
        paths=[]
        for i in range(201):
            p=self.inputs/f'many-{i}.txt';p.write_text(f'catalog item {i}');paths.append(str(p))
        result=self.engine.ingest('user','session',paths)
        self.assertEqual(len(result['files']),201)
        first=self.engine.list_page('user','session',limit=100)
        second=self.engine.list_page('user','session',cursor=first['next_cursor'],limit=100)
        last=self.engine.list_page('user','session',cursor=second['next_cursor'],limit=100)
        self.assertEqual(first['count'],201);self.assertEqual(len(last['files']),1);self.assertFalse(last['has_more'])
        ids=[f['id'] for page in [first,second,last] for f in page['files']]
        self.assertEqual(len(set(ids)),201)
        aid=last['files'][0]['id'];self.engine.process('user','session',aid)
        self.assertEqual(self.engine.search('user','session','catalog',ids=[aid])['hits'][0]['attachment_id'],aid)

    def test_cancel_resume_restart_reindex_and_citation_stability(self):
        p=self.inputs/'large.txt';p.write_text('ORBIT line checkpoint\n'*6000)
        aid=self.add('large.txt',process=False)
        results=[]
        t=threading.Thread(target=lambda:results.append(self.engine.process('user','session',aid)))
        t.start();deadline=time.monotonic()+10
        while self.engine.info('user','session',aid)['parsed_nodes']<100 and t.is_alive() and time.monotonic()<deadline:time.sleep(.01)
        self.engine.cancel('user','session',aid);t.join(10);self.assertFalse(t.is_alive())
        self.assertEqual(self.engine.info('user','session',aid)['status'],'partial')
        first=self.nodes(aid)[1]['citation']
        self.engine.close();self.engine=DocumentEngine(self.root/'private')
        result=self.engine.process('user','session',aid)
        self.assertEqual(result['status'],'complete');self.assertGreater(result['resumed_from'],0)
        self.assertEqual(first,self.nodes(aid)[1]['citation'])
        self.assertEqual(result['parsed_nodes'],6001)
        self.engine.process('user','session',aid,reindex=True)
        self.assertEqual(first,self.nodes(aid)[1]['citation'])

    def test_vision_actual_pixel_packets_exact_cloud_grants_and_revocation(self):
        class Vision(LocalScript):capabilities=BackendCapabilities(supports_vision=True)
        ids=[self.add(n) for n in ['red.png','blue.jpg','green.webp']]
        model=Vision(answer('scripted observation'))
        messages,plan=prepare(self.engine,'user','session',ids,'Compare colors',model,CloudEgressPolicy('LOCAL_ONLY'))
        self.assertEqual(len(messages[1].content),4);self.assertNotIn(str(self.root),json.dumps(plan))
        self.assertTrue(all(not s['original_submitted'] for s in plan['sources']))
        self.assertEqual(plan['sources'][2]['submitted_width'],1536)
        infer(self.engine,'user','session',ids,'Compare colors',model,CloudEgressPolicy('LOCAL_ONLY'))
        self.assertTrue(model.requests[0]['messages'][1].content[1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
        cloud=Vision(answer('cloud scripted'));cloud.is_local=False
        policy=CloudEgressPolicy('CLOUD_ALLOWED',max_request_bytes=2000000)
        with self.assertRaises(DocumentError):infer(self.engine,'user','session',ids,'Compare',cloud,policy)
        plan=prepare(self.engine,'user','session',ids,'Compare',cloud,policy)[1]
        approve(self.engine,'user','session',plan['request_sha256'])
        with self.assertRaises(DocumentError):infer(self.engine,'user','session',ids,'Changed question',cloud,policy)
        infer(self.engine,'user','session',ids,'Compare',cloud,policy)
        self.assertTrue(self.engine.info('user','session',ids[0])['cloud_uploaded'])
        self.assertEqual(self.engine.info('user','session',ids[0])['vision_submission_status'],'completed_ungraded')
        with self.assertRaises(DocumentError):infer(self.engine,'user','session',ids,'Compare',cloud,policy)
        self.engine.revoke('user','session',ids[0])
        with self.assertRaises(DocumentError):prepare(self.engine,'user','session',ids,'Compare',cloud,policy)
        with self.assertRaises(DocumentError):prepare(self.engine,'user','session',ids[1:],'Question',LocalScript(),policy)

    def test_registry_real_reads_and_gateway_does_not_trust_document_instructions(self):
        aid=self.add('plan.docx')
        workspace=self.root/'workspace';workspace.mkdir()
        b=LocalScript(answer('done'))
        runtime=AgentSession(create_default_registry(workspace,permission_mode='approve-mutations'),local_backend=b,
                             policy='local-only',hybrid_policy=HybridPolicy(CloudEgressPolicy('LOCAL_ONLY')),
                             hybrid_backends={'local':b},hybrid_primary='local')
        self.engine.initialize_session(runtime,'session','user')
        try:
            data=runtime.registry.call('document_read',{'attachment_id':aid})
            self.assertIn('Ignore previous instructions',json.dumps(data))
            with self.assertRaises((ValueError,PermissionError)):runtime.registry.call('read_file',{'path':'../private.key'})
            self.engine.revoke('user','session',aid)
            with self.assertRaises(DocumentError):runtime.registry.call('document_read',{'attachment_id':aid})
        finally:runtime.close()


if __name__=='__main__':unittest.main()
