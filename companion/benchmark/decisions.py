"""Host interpretation is deterministic; model confidence is not calibrated."""
import json

ACTIONS={'quiet','remind','offer_help','escalate'}


def parse_decision(result):
    if result.get('status')!='ok':return None
    try:
        data=json.loads(result['text'])
        if set(data)!={'action','confidence'} or data['action'] not in ACTIONS or type(data['confidence']) not in (int,float) or not 0<=data['confidence']<=1:return None
        return data
    except (ValueError,TypeError,KeyError):return None


def guard(event, decision, threshold=0.9):
    if event.get('dnd') or event.get('busy') or event.get('presentation') or event.get('kind') in {'save','browse','batch','unimportant'}:return 'quiet'
    if decision is None or decision['confidence']<threshold:return 'quiet'
    return decision['action']
