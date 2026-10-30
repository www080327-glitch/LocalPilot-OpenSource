"""Admission decisions over a host registry; no model downloads or fallback."""
from localpilot_api.service import APIError

SOURCES = ('local_only', 'local_first', 'balanced', 'cloud_first', 'cloud_only')
OBJECTIVES = ('speed', 'quality', 'efficiency', 'balanced')

def routing_contract():
    return {'version':'1.0', 'task_create_field':'routing_preferences',
            'sources':list(SOURCES), 'objectives':list(OBJECTIVES),
            'evidence_field':'service.route_decision.routing_preferences',
            'strategy':'deterministic_host_rank_v1',
            'thinking_scope':'host_route_configuration',
            'optimization_claim':'host priorities; no measured performance guarantee'}

def validate_preferences(value):
    if value is None: return None
    if (not isinstance(value, dict) or set(value)!={'version','source','objective'} or
        value['version']!='1.0' or value['source'] not in SOURCES or value['objective'] not in OBJECTIVES):
        raise APIError('Invalid routing_preferences 1.0', 'invalid_routing_preferences')
    return dict(value)

def is_cloud(entry):
    return entry.get('adapter') in {'deepseek','deepseek-native','remote-openai','remote-vllm'} or entry.get('cloud_egress') != 'LOCAL_ONLY'

def select_route(routes, catalog, *, explicit=None, preferences=(), required=(), routing_preferences=None):
    policy = validate_preferences(routing_preferences)
    if explicit is not None and (not isinstance(explicit, str) or explicit not in routes):
        raise APIError("Model/route is not registered for this client", "model_not_registered", 404)
    if not isinstance(preferences, (list, tuple)) or not all(isinstance(p, str) for p in preferences):
        raise APIError("model_preferences must be model IDs")
    if not isinstance(required, (list, tuple)) or not all(isinstance(c, str) for c in required):
        raise APIError("required_capabilities must be strings")
    candidates = [explicit] if explicit is not None else list(dict.fromkeys([p for p in preferences if p in routes] + list(routes)))
    if policy and explicit is None:
        def rank(public):
            entry = catalog.get(routes[public], {})
            cloud = is_cloud(entry)
            source = policy['source']
            source_rank = int(cloud) if source=='local_first' else int(not cloud) if source=='cloud_first' else 0
            return (source_rank, -entry.get('routing_rank', {}).get(policy['objective'], 0), candidates.index(public))
        candidates = sorted(candidates, key=rank)
    decisions = []
    for public in candidates:
        entry = catalog.get(routes[public], {})
        status = entry.get("deployment_status", "ready")
        # A local primary with an approved cloud partner is hybrid, not pure
        # cloud. Egress permission alone cannot establish provider location.
        pure_cloud = entry.get('adapter') in {'deepseek','deepseek-native','remote-openai','remote-vllm'}
        forbidden = policy and ((policy['source']=='local_only' and is_cloud(entry)) or (policy['source']=='cloud_only' and not pure_cloud))
        reason = 'model_source_forbidden' if forbidden else "model_not_deployed" if status in {"not_deployed", "downloading", "loading"} else "model_unavailable" if status != "ready" else "model_capability_insufficient" if set(required) - set(entry.get("capabilities", [])) else "selected"
        decisions.append({"model": public, "reason": reason})
        if reason == "selected":
            return public, {"selection": "explicit" if explicit else "preference" if public in preferences else "automatic",
                            "selected": public, "backend_model": entry.get("model", "UNKNOWN"),
                            "decisions": decisions, "backend_fallback": False,
                            **({'routing_preferences':policy, 'strategy':'deterministic_host_rank_v1',
                                'reason':'已按会话来源限制核对用户指定模型' if explicit else '先满足来源限制，再按所选优化目标的主机优先级选择；同分保持注册顺序',
                                'objective_priority':entry.get('routing_rank', {}).get(policy['objective'],0),
                                'thinking':{'effective':entry.get('thinking'), 'scope':'host_route_configuration'}} if policy else {})}
        if explicit:
            raise APIError("Explicit model cannot satisfy this request: " + reason, reason, 409)
    raise APIError("No eligible deployed model/route", decisions[-1]["reason"] if decisions else "model_unavailable", 503)
