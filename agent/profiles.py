"""Prompt text and tool descriptions are independent experimental variables."""

from .system_prompt import SYSTEM_PROMPT, MINIMAL_SYSTEM_PROMPT, DESKTOP_MINIMAL_SYSTEM_PROMPT

PROMPT_PROFILES = {
    "standard": SYSTEM_PROMPT,
    "minimal_0": "",
    "minimal_1": MINIMAL_SYSTEM_PROMPT,
    "minimal_agent_v2": DESKTOP_MINIMAL_SYSTEM_PROMPT,
}
TOOL_PROFILES = ("full", "compact")


def prompt_text(profile):
    try:
        return PROMPT_PROFILES[profile]
    except KeyError as error:
        raise ValueError(f"Unknown prompt profile: {profile}") from error
