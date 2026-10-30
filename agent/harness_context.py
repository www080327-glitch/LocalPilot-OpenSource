"""Opt-in request-view projection; canonical records and authority stay intact."""
from copy import deepcopy
from .context import ContextTooSmall,transfer_context
from .finalization import sha


def trim_optional_state(state):
    """Remove one oldest completed observation, never an obligation/UNKNOWN."""
    projected=deepcopy(state)
    contracts=[]
    def visit(value,path):
        if not isinstance(value,dict):return
        if value.get('model_handoff_version')==1:
            contracts.append((value,path))
            visit(value.get('parent_handoff'),path+'.parent_handoff')
        else:visit(value.get('model_handoff'),path+'.model_handoff')
    visit(projected,'state')
    for contract,path in contracts:
        for name in ('completed_steps','verified_evidence'):
            rows=contract.get(name) or []
            index=next((i for i,r in enumerate(rows) if r.get('status')=='completed' and r.get('effect') not in {'unknown','partial'} and r.get('verification')!='unknown'),None)
            if index is None:continue
            source_sha=contract.get('context_projection',{}).get('source_contract_sha256') or sha(contract)
            before={r.get('receipt_id') for field in ('completed_steps','verified_evidence','failed_unknown_actions') for r in contract.get(field,[]) if r.get('receipt_id')}
            removed=rows.pop(index)
            after={r.get('receipt_id') for field in ('completed_steps','verified_evidence','failed_unknown_actions') for r in contract.get(field,[]) if r.get('receipt_id')}
            contract['omitted_receipts']=contract.get('omitted_receipts',0)+len(before-after)
            marker=contract.setdefault('context_projection',{'lossy':True,'source_contract_sha256':source_sha,'omitted_optional_count':0,'omitted_optional_sha256':None,
                'instruction':'Only completed optional excerpts were omitted. Omitted evidence is unavailable, never PASS; inspect current files. Obligations/UNKNOWN/permissions/budgets remain complete; canonical receipts were not changed.'})
            marker['omitted_optional_count']+=1
            marker['omitted_optional_sha256']=sha([marker['omitted_optional_sha256'],path+'.'+name,removed])
            return projected
    return None


def transfer_with_optional_projection(messages,tools,window,output_reserve,*,enabled=False,**kwargs):
    """Same byte admission and output guard; fail closed if critical state fails."""
    state=kwargs.get('working_state');reductions=0
    for _ in range(193):
        try:
            view,info=transfer_context(messages,tools,window,output_reserve,**{**kwargs,'working_state':state})
            if reductions:
                info={**(info or {}),'optional_completed_context_entries_omitted':reductions,
                    'canonical_history_changed':False,'critical_obligations_changed':False,
                    'estimator':'utf8_bytes_conservative_not_measured_tokens'}
            return view,info
        except ContextTooSmall:
            if not enabled:raise
            next_state=trim_optional_state(state)
            if next_state is None:raise
            state=next_state;reductions+=1
    raise ContextTooSmall('Bounded optional projection exhausted; critical state not truncated.')
