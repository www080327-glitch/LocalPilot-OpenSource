"""Fail-closed comparison audit. No comparison is accepted on identity claims alone."""
import argparse
import json
from pathlib import Path


def compare(a,b,allow_retrieval_difference=False):
    ra={r['id']:r for r in a.get('rows',[])};rb={r['id']:r for r in b.get('rows',[])}
    checks={'completed':a.get('status')==b.get('status')=='completed',
            'same_suite':bool(a.get('suite_sha256')) and a.get('suite_sha256')==b.get('suite_sha256'),
            'same_fixtures':bool(a.get('fixture_sha256')) and a.get('fixture_sha256')==b.get('fixture_sha256'),
            'same_generation':bool(a.get('generation')) and a.get('generation')==b.get('generation'),
            'same_case_ids':bool(ra) and set(ra)==set(rb),
            'same_retrieval':a.get('retrieval_backend')==b.get('retrieval_backend'),
            'model_identity_recorded':bool(a.get('identity_sha256')) and bool(b.get('identity_sha256')),
            'same_hardware':a.get('identity',{}).get('hardware')==b.get('identity',{}).get('hardware')}
    mismatches=[k for k in ra.keys()&rb.keys() if ra[k]['prompt_sha256']!=rb[k]['prompt_sha256']]
    checks['same_prompts']=not mismatches and bool(ra)
    if allow_retrieval_difference:
        checks['same_retrieval']=True
        checks['same_prompts']=all(ra[k]['prompt_sha256']==rb[k]['prompt_sha256'] for k in ra.keys()&rb.keys() if ra[k]['category'] not in {'memory','restart'})
    return {'status':'accepted_diagnostic_comparison' if all(checks.values()) else 'BLOCKED',
            'checks':checks,'prompt_mismatches':mismatches,'retrieval_ablation':allow_retrieval_difference,
            'accepted_speedup':None,'speedup_status':'NOT_ESTABLISHED: desktop interference and different output lengths; this audit accepts diagnostic scores only'}


def main():
    p=argparse.ArgumentParser();p.add_argument('first');p.add_argument('second');p.add_argument('--output',required=True);p.add_argument('--retrieval-ablation',action='store_true');a=p.parse_args()
    result=compare(json.loads(Path(a.first).read_text()),json.loads(Path(a.second).read_text()),a.retrieval_ablation)
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
    if result['status']=='BLOCKED':raise SystemExit(1)

if __name__=='__main__':main()
