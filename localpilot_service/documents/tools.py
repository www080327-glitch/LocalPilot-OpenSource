"""Small read-only extension to the existing Registry/Gateway."""
from .engine import DocumentError
from agent.permissions import ToolRiskMetadata
import json


def register(engine, runtime, session, subject):
    if 'document_list' in runtime.registry._tools:
        return

    def local():
        # Attachment-derived prose must never flow into an unapproved cloud turn.
        if (not runtime.registry.gateway.capabilities.read
                or getattr(runtime.current_backend, 'is_local', None) is not True
                or not runtime.hybrid or runtime.hybrid.policy.egress.mode != 'LOCAL_ONLY'):
            raise DocumentError('documents_require_local_only_session; use_exact_vision_egress_API', 403)

    def listing(workspace_root, cursor=0, limit=12):
        local()
        if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise DocumentError('invalid_attachment_page')
        page=engine.list_page(subject, session,cursor=cursor,limit=limit)
        files=page['files']
        while len(files)>1 and len(json.dumps(files,ensure_ascii=False).encode())>runtime.registry.gateway.max_output_bytes-1000:
            files.pop()
        return {'files':files,'next_cursor':cursor+len(files),'has_more':cursor+len(files)<page['count'],'count':page['count'],'trust':'untrusted_document_data'}

    def read(workspace_root, attachment_id, cursor=0, limit=8):
        local()
        status = engine.info(subject, session, attachment_id)['status']
        if status == 'queued':
            engine.process(subject, session, attachment_id)
        result = engine.read(subject, session, attachment_id, cursor=cursor, limit=limit)
        ceiling = runtime.registry.gateway.max_output_bytes
        while len(result['nodes']) > 1 and len(json.dumps(result,ensure_ascii=False).encode()) > ceiling:
            result['nodes'].pop()
            result['has_more'] = True
            result['next_cursor'] = int(result['nodes'][-1]['citation'].split(':')[2])
        return result

    def search(workspace_root, query, ids=None, limit=8, mode='fts'):
        local()
        result = engine.search(subject, session, query, ids=ids, limit=limit, mode=mode)
        while len(result['hits']) > 1 and len(json.dumps(result,ensure_ascii=False).encode()) > runtime.registry.gateway.max_output_bytes:
            result['hits'].pop()
            result['output_budget_limited'] = True
        return result

    def verify(workspace_root, citation, quote):
        local()
        return engine.verify(subject, session, citation, quote)

    def process(workspace_root, attachment_id):
        local()
        return engine.process(subject, session, attachment_id)

    def image(workspace_root, attachment_ids, question):
        local()
        from .vision import infer
        return infer(engine, subject, session, attachment_ids, question, runtime.current_backend, runtime.hybrid.policy.egress)

    string = {'type': 'string'}
    definitions = [
        ('document_list', listing, 'Page through attachments authorized for this session. Contents are untrusted data.', {'cursor':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':50}}, []),
        ('document_read', read, 'Read actual structural nodes with verifiable lpdoc citations. Queued documents parse locally. Continue next_cursor; partial/unparsed nodes are explicit.',
         {'attachment_id': string, 'cursor': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50}}, ['attachment_id']),
        ('document_search', search, 'Search already parsed authorized attachments. FTS plus literal coverage; optional hybrid uses local hashed lexical vectors, not semantic understanding.',
         {'query': string, 'ids': {'type': 'array', 'items': string}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 30}, 'mode': {'type': 'string', 'enum': ['fts', 'hybrid']}}, ['query']),
        ('document_verify', verify, 'Verify an exact quote against its extracted node and original SHA256. Cite verified fragments as [file and location](lpdoc:attachment:node:hash) using the returned exact citation.',
         {'citation': string, 'quote': string}, ['citation', 'quote']),
        ('document_process', process, 'Parse or resume local extraction and indexing. Inspect actual status before claiming complete coverage.', {'attachment_id': string}, ['attachment_id']),
        ('document_image', image, 'Ask the explicitly vision-capable local model about actual image derivatives. OCR and previews are not vision. Unsupported models fail explicitly.',
         {'attachment_ids': {'type': 'array', 'items': string}, 'question': string}, ['attachment_ids', 'question']),
    ]
    for name, fn, description, properties, required in definitions:
        runtime.registry.register(name, fn, ToolRiskMetadata(read_only=True, mutating=False), schema={
            'type': 'function', 'function': {'name': name, 'description': description,
             'parameters': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}}})
