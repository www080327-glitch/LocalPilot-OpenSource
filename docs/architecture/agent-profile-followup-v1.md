# Agent profile follow-up v1 — 2026-10-24

Status: contract frozen before implementation. Standard is the default. Standard and minimal are the same Core AgentSession with the same permitted tool schemas, Gateway, receipts and verification. Minimal uses a short complete prompt, without appending the standard prompt. Companion is absent from normal chat. Switching profiles is a UI preference, without task or permission approval. Cloud egress and real tool approvals remain independent.

Additive capability: `desktop_profile_switch_v1`. Operator-only `POST /localpilot/v1/desktop-sessions/{id}/profile`, body `{client_subject, agent_profile, expected_profile}`. Exact owner and operator approval_for binding required. The session must have no active task or pending control. Change only the prompt profile at a quiescent boundary; preserve messages, model, tool schemas, Gateway policy and receipts. Compare expected_profile (or return current if already applied); do not resubmit tasks. Atomically checkpoint before returning; audit old/new profiles. Task metadata freezes the profile used for each turn.

New Desktop sessions store server-owned prompt_revision=2. Older checkpoints without it keep revision 1 semantics; switching explicitly upgrades that session. Revision 2 minimal uses minimal_1 and a concise complete V5 prompt; legacy minimal_0 is unchanged. The switch changes configuration fingerprint through the existing persistence implementation and must restore without losing history.

Suite operation `desktop_profile` validates the exact body and uses the operator client. Desktop capability-negotiates before switching a started session; never silently starts a blank replacement conversation. New-session selection does not call a model.

Local installation: preserve the verified old ~/Applications/LocalPilot.app as a versioned backup, replace its original entry with the verified new build, refresh Launch Services, then verify the launched executable/version and normal GUI. Preserve Application Support and history. No formal Release. Publish source changes through an integration branch in the existing GitHub repository, retaining independent module directories and source hashes.

Compatibility refinement before delivery: revision 2 uses the additive `minimal_agent_v2` profile rather than reusing `minimal_1`. Both historical minimal_0 and minimal_1 keep their original text and assembly behavior, preserving old CLI/Companion configuration fingerprints. Only an explicit Desktop selection opts into the new prompt.
