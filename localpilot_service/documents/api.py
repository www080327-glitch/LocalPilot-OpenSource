"""Authenticated Attachment API v2, independent of v1 workspace copies."""
from agent.persistence import configuration, digest, dumps
from localpilot_api.service import APIError
from .engine import DocumentError


def handle(server, principal, body):
    if not isinstance(body, dict) or not {'operation', 'session_id'} <= body.keys():
        raise APIError('Document operation and session required')
    if not isinstance(body['operation'],str) or not isinstance(body['session_id'],str):
        raise APIError('Document operation and session must be strings')
    engine = getattr(server.service, 'documents', None)
    if engine is None:
        raise APIError('Document Engine is unavailable in this deployment', 'document_engine_unavailable', 503)
    subject = body.get('client_subject', principal.subject)
    if subject != principal.subject and (not principal.operator or subject not in principal.approval_for):
        raise APIError('Document owner denied', 'scope_forbidden', 403)
    sid, op = body['session_id'], body['operation']
    session = server.service._session(sid)
    if session.owner_subject != subject:
        raise APIError('Session owner denied', 'scope_forbidden', 403)
    options = {k:v for k,v in body.items() if k not in {'client_subject','session_id','operation'}}
    control = op in {'import','revoke','gc','vision_approve','vision_infer'}
    if control and (not principal.operator or 'control' not in principal.scopes or subject not in principal.approval_for):
        raise APIError('Separate operator authorization required', 'control_required', 403)
    if not control and 'read' not in principal.scopes:
        raise APIError('Read scope required', 'scope_forbidden', 403)
    try:
        if op == 'import':
            if set(options) - {'paths','origin','origins','ttl_seconds'} or 'paths' not in options:
                raise DocumentError('invalid_import_fields')
            runtime = session.runtime
            if (getattr(runtime.current_backend,'is_local',None) is not True or not runtime.hybrid
                    or runtime.hybrid.policy.egress.mode != 'LOCAL_ONLY'):
                raise DocumentError('document_import_requires_local_only_session', 403)
            with server.service.condition:
                if session.active_task:
                    raise DocumentError('finish_active_task_before_import', 409)
                result = engine.ingest(subject, sid, **options)
                session.extensions = {**(session.extensions or {}), 'documents':2}
                runtime._service_extensions = dict(session.extensions)
                engine.initialize_session(runtime, sid, subject)
                if server.service.store:
                    runtime._persistence_config = digest(dumps(configuration(runtime)))
                    server.service._checkpoint(sid, 'document_extension_v2_bound')
        elif op in {'vision_plan','vision_approve','vision_infer'}:
            from .vision import prepare, approve, infer
            if op == 'vision_approve':
                if set(options) != {'request_sha256'}:
                    raise DocumentError('exact_vision_digest_required')
                result = approve(engine, subject, sid, options['request_sha256'])
            else:
                if set(options) != {'model','attachment_ids','question'}:
                    raise DocumentError('exact_vision_request_required')
                client = server.access.principals[subject]
                if options['model'] not in client.routes:
                    raise DocumentError('vision_route_not_registered', 404)
                runtime = server.service.routes[client.routes[options['model']]](lambda e: None)
                try:
                    if not runtime.hybrid:
                        raise DocumentError('vision_egress_policy_required', 403)
                    args = (engine, subject, sid, options['attachment_ids'], options['question'], runtime.current_backend, runtime.hybrid.policy.egress)
                    result = prepare(*args)[1] if op == 'vision_plan' else infer(*args)
                finally:
                    runtime.close()
        elif op == 'gc':
            if options:
                raise DocumentError('gc_has_no_options')
            result = engine.gc()
        elif op in {'list', 'status','read','process','reindex','search','verify','cancel','revoke'}:
            fields = {'list':{'cursor','limit'}, 'status':{'attachment_id'}, 'read':{'attachment_id','cursor','limit'},
                      'process':{'attachment_id'}, 'reindex':{'attachment_id'}, 'search':{'query','ids','limit','mode'},
                      'verify':{'citation','quote'}, 'cancel':{'attachment_id'}, 'revoke':{'attachment_id'}}
            if set(options) - fields[op]:
                raise DocumentError('unknown_document_fields')
            if op == 'list': result = engine.list_page(subject, sid, **options)
            elif op == 'search': result = engine.search(subject, sid, **options)
            elif op == 'verify': result = engine.verify(subject, sid, **options)
            else:
                aid = options.pop('attachment_id')
                if op == 'status': result = engine.info(subject, sid, aid)
                elif op == 'read': result = engine.read(subject, sid, aid, **options)
                elif op in {'process','reindex'}: result = engine.process(subject, sid, aid, reindex=op=='reindex')
                elif op == 'cancel': result = engine.cancel(subject, sid, aid)
                else: result = engine.revoke(subject, sid, aid)
        else:
            raise DocumentError('unknown_document_operation')
        result = {'version':'2.0', **result}
        disclosure = ({'request_sha256':result.get('request_sha256'),'bytes':result.get('bytes'),
                       'provider_model':result.get('provider',{}).get('model'),
                       'cloud_approval_required':result.get('cloud_approval_required')}
                      if op.startswith('vision_') else {})
        server.access.audit(operation='document_v2_'+op, subject=principal.subject, client_subject=subject, session_id=sid, **disclosure)
        return result
    except DocumentError as e:
        raise APIError(e.code, e.code.split(';')[0], e.status) from None
    except (KeyError, TypeError):
        raise APIError('Invalid document operation fields') from None
