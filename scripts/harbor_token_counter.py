"""Text-only tokenizer process; loads tokenizer files, never model weights."""
import json
import sys

from transformers import AutoTokenizer
from omlx.api.openai_models import Message
from omlx.api.tool_calling import convert_tools_for_template
from omlx.api.utils import extract_multimodal_content, prepare_system_messages_for_template

tokenizer = AutoTokenizer.from_pretrained(sys.argv[1], local_files_only=True, trust_remote_code=False)
for line in sys.stdin:
    try:
        data = json.loads(line)
        tools = convert_tools_for_template(data.get('tools'))
        messages = extract_multimodal_content([Message(**m) for m in data['messages']],
            tokenizer=tokenizer, consolidate_system_messages=False)
        messages = prepare_system_messages_for_template(messages, tokenizer, tools=tools,
            chat_template_kwargs=data.get('chat_template_kwargs'), merge_consecutive_roles=False)
        prompt = tokenizer.apply_chat_template(messages, tools=tools,
            tokenize=False, add_generation_prompt=True, **data.get('chat_template_kwargs', {}))
        result = {'input_tokens':len(tokenizer.encode(prompt))}
    except Exception as error:
        result = {'error':type(error).__name__ + ': ' + str(error)}
    print(json.dumps(result), flush=True)
