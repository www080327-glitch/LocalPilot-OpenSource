"""Application-specific read contracts, never claims of measured AX coverage.

Summaries are derived from already admitted, filtered AX rows. They do not open
documents, inspect browser profiles, retrieve URLs, or infer a user's intent.
The native provider applies the same pruning before descendant getters.
"""
from dataclasses import dataclass
import re


PROFILE_VERSION = 1
SENSITIVE_WINDOW = re.compile(
    r"password|passwd|passphrase|cookie|keychain|credential|"
    r"(?:access|refresh|login|auth|bearer)[ _-]*token|api[ _-]*key|"
    r"authorization\s*:|bearer\s+\S+|sk-[A-Za-z0-9_-]{12,}|"
    r"-----BEGIN[^\n]*PRIVATE KEY|密码|口令|密钥|令牌|"
    r"(?:^|[/_. -])(?:id_rsa|id_ed25519|secrets?|credentials?)(?:$|[/_. -])|"
    r"\.(?:env|pem|key|p12|pfx)(?:$|\s|[—–-])", re.I)
INPUT_ROLES = frozenset({"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField", "AXSecureTextField"})
PAGE_LABEL = re.compile(r"^(?:Page\s+(\d+)\s+(?:of|/)\s+(\d+)|第\s*(\d+)\s*页\s*[,，/]\s*(?:共\s*)?(\d+)\s*页)$", re.I)
ERROR_LABEL = re.compile(r"^(?:Error|错误|失败)\s*[:：]\s*\S", re.I)


@dataclass(frozen=True)
class AppProfile:
    id: str
    bundles: tuple
    kind: str
    denied_roles: frozenset
    denied_subroles: frozenset
    limits: tuple

    def describe(self):
        return {"id": self.id, "version": PROFILE_VERSION, "bundles": list(self.bundles),
                "kind": self.kind, "denied_roles": sorted(self.denied_roles),
                "denied_subroles": sorted(self.denied_subroles), "limitations": list(self.limits),
                "implementation": "IMPLEMENTED", "real_app_validation": "MANUAL_REQUIRED"}


_DIALOGS = frozenset({"AXSheet", "AXDialog", "AXPopover"})
_PRIVATE_SUBROLES = frozenset({"AXSecureTextField", "AXDialog", "AXSystemDialog"})
PROFILES = (
    AppProfile("finder", ("com.apple.finder",), "file_browser", _DIALOGS, _PRIVATE_SUBROLES,
               ("directory_path_UNKNOWN", "file_metadata_requires_authorized_file_observer", "AX_provider_coverage_PARTIAL")),
    AppProfile("safari", ("com.apple.Safari",), "browser", _DIALOGS, _PRIVATE_SUBROLES,
               ("URL_NOT_READ", "DOM_NOT_READ", "Cookie_NOT_READ", "page_text_only_if_exposed_as_AXStaticText")),
    AppProfile("chrome", ("com.google.Chrome", "org.chromium.Chromium"), "browser", _DIALOGS, _PRIVATE_SUBROLES,
               ("URL_NOT_READ", "DOM_NOT_READ", "Cookie_NOT_READ", "page_text_only_if_exposed_as_AXStaticText")),
    AppProfile("vscode", ("com.microsoft.VSCode", "com.microsoft.VSCodeInsiders"), "ide",
               _DIALOGS | {"AXOutline", "AXTable"}, _PRIVATE_SUBROLES,
               ("editor_input_NOT_READ", "terminal_input_NOT_READ", "file_explorer_pruned", "file_path_UNKNOWN", "diagnostic_cause_UNKNOWN")),
    AppProfile("preview", ("com.apple.Preview",), "document_viewer", _DIALOGS, _PRIVATE_SUBROLES,
               ("PDF_path_NOT_READ", "selected_text_NOT_READ", "body_only_if_AXStaticText", "page_count_UNKNOWN_unless_explicit_UI_label")),
    AppProfile("textedit", ("com.apple.TextEdit",), "text_editor", _DIALOGS, _PRIVATE_SUBROLES,
               ("editable_body_NOT_READ", "selected_text_NOT_READ", "document_path_UNKNOWN", "save_state_UNKNOWN")),
)
FALLBACK = AppProfile("generic", (), "generic", _DIALOGS, _PRIVATE_SUBROLES,
                      ("AX_provider_coverage_PARTIAL", "document_path_UNKNOWN", "task_state_UNKNOWN"))


def app_profile(bundle):
    return next((p for p in PROFILES if bundle in p.bundles), FALLBACK)


def window_qualified(title, exact_titles=()):
    """Title is eligibility metadata; rejected raw text must not enter logs."""
    return (isinstance(title, str) and len(title) <= 300
            and not any(ord(c) < 32 for c in title)
            and not SENSITIVE_WINDOW.search(title)
            and (not exact_titles or title in exact_titles))


def compact_nodes(nodes, limit=64, max_bytes=6000):
    """Select already admitted text with ancestors; no AX reads happen here."""
    import json
    by_id = {n["id"]: n for n in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("Duplicate admitted node identity")
    costs = {n["id"]:len(json.dumps(n, ensure_ascii=False).encode())+2 for n in nodes}
    selected = set()
    priority = [n for n in nodes if n.get("role") == "AXWindow"]
    priority += sorted((n for n in nodes if n.get("role") == "AXStaticText" and n.get("text")),
                       key=lambda n: -len(n["text"]))
    priority += nodes
    for node in priority:
        if len(selected) >= limit:
            break
        chain, current = set(), node
        while current["id"] not in selected:
            if current["id"] in chain:
                break
            chain.add(current["id"])
            parent = current.get("parent")
            if parent is None:
                break
            current = by_id[parent]
        proposed = selected | chain
        if len(proposed) <= limit and sum(costs[i] for i in proposed) <= max_bytes:
            selected.update(chain)
    return [n for n in nodes if n["id"] in selected]


def summarize_observation(bundle, nodes, title=None, read_status="UNKNOWN"):
    """Bounded factual context after privacy/byte trimming, not model inference."""
    profile = app_profile(bundle)
    counts = {}
    static = []
    for node in nodes:
        role = node.get("role")
        if isinstance(role, str):
            counts[role] = counts.get(role, 0) + 1
        if role == "AXStaticText" and isinstance(node.get("text"), str):
            static.append(node)
    result = {"profile": profile.id, "profile_version": PROFILE_VERSION, "kind": profile.kind,
              "coverage": "PARTIAL", "read_status": read_status,
              "role_counts": dict(list(sorted(counts.items()))[:20]), "static_text_nodes": len(static),
              "document_state": "UNKNOWN", "task_state": "UNKNOWN", "document_path": "UNKNOWN",
              "error_label_node_ids": [n["id"] for n in static if ERROR_LABEL.search(n["text"])][:8]}
    if title is not None:
        # A window title is a UI label. It is not a verified path/project/URL.
        result["title_semantics"] = "page_title_label" if profile.kind == "browser" else "window_title_label"
    if profile.kind == "document_viewer":
        pages = set()
        for node in static:
            match = PAGE_LABEL.fullmatch(node["text"].strip())
            if match:
                current, total = [int(n) for n in match.groups() if n is not None]
                if 1 <= current <= total <= 100000:
                    pages.add((current, total))
        if len(pages) == 1:
            current, total = next(iter(pages))
            result.update(displayed_page=current, displayed_page_count=total, page_evidence="explicit_static_UI_label")
        else:
            result["displayed_page_count"] = "UNKNOWN"
    return result
