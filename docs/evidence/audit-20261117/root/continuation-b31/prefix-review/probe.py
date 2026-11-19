from agent.backends import Message
from agent.context_v5 import transfer
from agent.openai_responses import OpenAIResponsesBackend
from tests.test_openai_responses import response_payload
backend=OpenAIResponsesBackend(model='gpt-6-luna',api_key='synthetic-only-no-network')
history=[Message('system','stable instructions'),Message('user','Read fact.txt')]
first,_=transfer(history,[],5000,500,working_state={'budget':1})
first_wire=backend._payload(first,tools=[],thinking='medium')['input']
reply=backend._response(response_payload(call=True))
history.extend([reply.message,Message('tool','synthetic fact',tool_call_id='call_fixture')])
second,_=transfer(history,[],5000,500,working_state={'budget':2})
second_wire=backend._payload(second,tools=[],thinking='medium')['input']
reasoning_index=next(i for i,item in enumerate(second_wire) if item.get('type')=='reasoning')
print({'network_calls':0,'first_input_items':len(first_wire),'second_prefix_before_reasoning_items':reasoning_index,'first_input_equals_prefix':first_wire==second_wire[:reasoning_index],'canonical_messages':len(history),'canonical_host_state_items':sum('Current Host state' in (m.content or '') for m in history),'second_has_encrypted_reasoning':any('encrypted_content' in item for item in second_wire),'second_has_function_call':any(item.get('type')=='function_call' for item in second_wire),'second_has_function_call_output':any(item.get('type')=='function_call_output' for item in second_wire)})
