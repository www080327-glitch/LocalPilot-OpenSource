from pathlib import Path
import json,importlib.metadata,time
from localpilot_service.cli import connection, compatible
base=Path(__file__).resolve().parent
home=base/'profile-e/client/product-v5'
client=connection(home)
health=compatible(client)
tasks=client.request('/localpilot/v1/tasks')['tasks']
record={'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'scope':'Read-only packaged service health and task inventory; no task or model request','health':health,'task_count':len(tasks),'module_versions':{name:importlib.metadata.version(name) for name in ['localpilot-agent-service','localpilot-suite','localpilot-companion','localpilot-channels']}}
(base/'service-capabilities.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'status':'PASS','task_count':len(tasks),'task_timeout_seconds':health.get('limits',{}).get('task_timeout_seconds'),'extended_budget_capability':'desktop_execution_budget_v1' in health.get('compatibility',{}).get('capabilities',[])}))
