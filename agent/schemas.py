"""Function-calling schemas shared by DeepSeek and OpenAI-style APIs."""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to the workspace root.",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List names in a directory inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to the workspace root; defaults to '.'.",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Find literal text in UTF-8 files inside the workspace; returns matching paths, line numbers, and short excerpts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Non-empty text to find."},
                    "path": {"type": "string", "description": "File or directory relative to the workspace root; defaults to '.'."},
                    "file_pattern": {"type": "string", "description": "Filename glob such as '*.py'; defaults to '*'."},
                    "case_sensitive": {"type": "boolean", "description": "Whether matching is case-sensitive; defaults to true."},
                    "max_results": {"type": "integer", "description": "Maximum matches to return, capped at 50; defaults to 50."},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_info",
            "description": "Return the relative path, file or directory type, and size for a workspace entry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory path relative to the workspace root."},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_SCHEMAS.extend([
    {
        "type": "function",
        "function": {
            "name": "execute",
            "description": "Run argv without a shell in the fixed workspace. Use cat/ls to inspect in Minimal. Policy can deny or require approval. Project scripts/tests execute code. No inline Python. Output is bounded.",
            "parameters": {
                "type": "object",
                "properties": {
                    "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 100},
                    "timeout": {"type": "number", "exclusiveMinimum": 0, "maximum": 30, "description": "Seconds; default 10."},
                    "output_limit": {"type": "integer", "minimum": 1, "maximum": 16000, "description": "Combined stdout/stderr bytes; default 16000."},
                },
                "required": ["argv"], "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "UTF-8 files. JSON: {\"changes\":[{\"path\":\"file.txt\",\"operation\":\"create\",\"content\":\"text\"}]}. operation belongs inside EVERY change. Inspect first; update old_text matches once. Delete requires expected_sha256. Parents must exist; no symlink writes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "changes": {
                        "type": "array", "minItems": 1, "maxItems": 20,
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "operation": {"type": "string", "enum": ["create", "update", "delete"]},
                                "content": {"type": "string", "description": "create only"},
                                "old_text": {"type": "string", "description": "update only; exact unique match"},
                                "new_text": {"type": "string", "description": "update only"},
                                "expected_sha256": {"type": "string", "description": "Optional stale-file guard; required for delete."},
                            },
                            "required": ["path", "operation"], "additionalProperties": False,
                        },
                    },
                },
                "required": ["changes"], "additionalProperties": False,
            },
        },
    },
])

# Dedicated bounded filesystem tools; renaming is a move in the same directory.
FILE_SCHEMAS = []
for _name, _description, _props, _required in [
    ('inspect_file','Inspect a file with identity and SHA-256 for safe move/copy.',{'path':{'type':'string'}},['path']),
    ('list_entries','List immediate filenames, types, sizes and modification times.',{'path':{'type':'string'}},[]),
    ('make_directory','Create one directory; parent must exist, never overwrite.',{'path':{'type':'string'}},['path']),
    ('move_file','Move file one regular file inside the authorized folder; inspect file_info first. Never overwrite.',{'source':{'type':'string'},'destination':{'type':'string'},'expected_sha256':{'type':'string','pattern':'^[0-9a-f]{64}$'}},['source','destination','expected_sha256']),
    ('copy_file','Copy file one regular file inside the authorized folder; inspect file_info first. Never overwrite.',{'source':{'type':'string'},'destination':{'type':'string'},'expected_sha256':{'type':'string','pattern':'^[0-9a-f]{64}$'}},['source','destination','expected_sha256']),
]:
    FILE_SCHEMAS.append({'type':'function','function':{'name':_name,'description':_description,'parameters':{'type':'object','properties':_props,'required':_required,'additionalProperties':False}}})
