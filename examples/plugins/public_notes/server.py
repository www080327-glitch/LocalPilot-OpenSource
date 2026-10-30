"""MIT; a standalone MCP plugin using fixed public data and no Core imports."""
from mcp.server.fastmcp import FastMCP

server = FastMCP("public-notes")
NOTES = {"mcp": "MCP connects hosts to tools, resources and prompts."}


@server.tool()
def lookup_public_note(topic: str) -> str:
    """Look up a fixed public note. No filesystem or network access is needed."""
    return NOTES.get(topic, "No public note for this topic")


@server.resource("public-note://mcp")
def public_note() -> str:
    return NOTES["mcp"]


@server.prompt()
def explain_public_note() -> str:
    return "Explain the public MCP note in plain language."


if __name__ == "__main__":
    server.run()
