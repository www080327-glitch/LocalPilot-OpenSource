"""Host verification of current bytes and exact scalar/quote locations.

Support means the cited document supports the claim, not that its author is right.
General paraphrase, OCR, computed formulas and implicit reasoning stay unverified.
"""
import hashlib
import json
import re
from pathlib import Path

from companion.observers.documents import extract
from .reliability import explicit_claims, scalar

STATUSES = {"SUPPORTED", "PARTIALLY_SUPPORTED", "UNVERIFIED", "CONTRADICTED"}


def normalized(value):
    return re.sub(r"\s+", "", str(value)).strip("。；; ")


def location_matches(claimed, actual):
    # A real page/slide can support a quote from any of its extracted lines.
    claimed, actual = normalized(claimed), normalized(actual)
    if claimed == actual:
        return True
    if re.fullmatch(r"(?:page|slide)\d+", claimed):
        return actual.split(";", 1)[0] == claimed
    if re.fullmatch(r"line\d+", claimed):
        return actual.split(";")[-1] == claimed
    return False


class SourceVerifier:
    def __init__(self, store, scope):
        self.store, self.scope = store, scope

    def verify(self, claim, allowed_ids=None):
        result = {"status": "UNVERIFIED", "reason": "incomplete_claim", "claim": claim,
                  "evidence_class": "INFERRED"}
        required = {"memory_id", "version_id", "file_hash", "source_file", "location", "value", "field"}
        if not isinstance(claim, dict) or set(claim) != required or any(not isinstance(claim[k], str) or not claim[k] for k in required):
            return result
        def verdict(status, reason, **extra):
            return result | {"status": status, "reason": reason} | extra
        if allowed_ids is not None and claim["memory_id"] not in allowed_ids:
            return verdict("UNVERIFIED", "source_not_in_answer_context")
        row = self.store.db.execute("SELECT * FROM memories WHERE id=?", (claim["memory_id"],)).fetchone()
        if not row or row["type"] != "document" or row["epistemic"] != "factual" or row["source"] != "document_extractor":
            return verdict("UNVERIFIED", "unknown_or_inferred_memory")
        meta = json.loads(row["metadata"])
        if row["source_reference"] != claim["source_file"]:
            return verdict("CONTRADICTED", "file_identity_mismatch")
        version = self.store.db.execute("SELECT * FROM source_versions WHERE memory_id=? AND id=?", (row["id"], claim["version_id"])).fetchone()
        if not version or not version["current"] or meta.get("version_id") != claim["version_id"]:
            return verdict("CONTRADICTED", "stale_or_wrong_version")
        if claim["file_hash"] != version["digest"]:
            return verdict("CONTRADICTED", "wrong_claimed_hash")
        if not self.scope.allowed(row["source_reference"]):
            return verdict("UNVERIFIED", "source_outside_read_scope")
        try:
            data, _ = self.scope.read(row["source_reference"])
            digest = hashlib.sha256(data).hexdigest()
            if digest != version["digest"]:
                self.store.invalidate_source(row["source_reference"])
                return verdict("CONTRADICTED", "current_bytes_changed")
            document = extract(data, Path(row["source_reference"]).suffix.lower(), self.scope.config.max_document_chars)
        except Exception:
            return verdict("UNVERIFIED", "source_unreadable")
        locations = [loc for loc in document.locations if location_matches(claim["location"], loc["location"])]
        if not locations:
            return verdict("UNVERIFIED" if document.truncated else "CONTRADICTED", "location_not_extracted_or_missing")
        if any(loc.get("incomplete") for loc in locations):
            return verdict("UNVERIFIED", "incomplete_extracted_location")
        fragments = [document.text[loc["start"]:loc["end"]].strip() for loc in locations]
        if claim["field"] == "quote":
            supported = any(normalized(claim["value"]) == normalized(f) or
                            normalized(claim["value"]) == normalized(re.sub(r"^\[(?:page|slide) [^\]]+\]\s*", "", f)) for f in fragments)
        elif claim["field"] in {"budget", "owner", "deadline"}:
            # Exact same-cell equality; a header/title or substring is insufficient.
            if document.structure["format"] == "xlsx":
                cell_match = re.fullmatch(r"sheet (.+) cell ([A-Z]+)(\d+)", claim["location"])
                headers = {"budget":{"预算", "budget"}, "owner":{"负责人", "owner"}, "deadline":{"截止日期", "deadline"}}
                header_ok = False
                if cell_match:
                    sheet, column, row_number = cell_match.groups()
                    sheet_text = next((part.split("\n", 1)[1] for part in re.split(r"\[sheet ", document.text)[1:]
                                       if part.startswith(sheet + "]\n")), "")
                    header_ok = any(int(number) < int(row_number) and value.strip().lower() in headers[claim["field"]]
                                    for number, value in re.findall(r"^" + re.escape(column) + r"(\d+): (.*)$", sheet_text, re.M))
                supported = any(scalar(claim["value"]) == scalar(re.sub(r"^[A-Z]+\d+:\s*", "", f).split(" [formula=", 1)[0]) for f in fragments)
                # Field must also be an explicitly labelled claim in this document.
                supported = supported and header_ok and any(key.endswith(":" + claim["field"]) and scalar(value) == scalar(claim["value"])
                                              for key, value in explicit_claims(document.text, claim["source_file"]))
            else:
                supported = any(key.endswith(":" + claim["field"]) and scalar(value) == scalar(claim["value"])
                                for fragment in fragments for key, value in explicit_claims(fragment, claim["source_file"]))
        else:
            return verdict("UNVERIFIED", "unsupported_semantic_field")
        if not supported:
            return verdict("CONTRADICTED", "value_not_supported_at_location")
        conflicts = self.store.active_conflicts(row["id"])
        conflicts = [c for c in conflicts if c["claim_key"].endswith(":" + claim["field"])]
        if conflicts:
            return verdict("PARTIALLY_SUPPORTED", "conflicting_current_sources", conflicts=conflicts)
        return verdict("SUPPORTED", "direct_current_source", evidence_class="OBSERVED")

    def verify_sources(self, sources):
        claims = []
        for source in sources:
            if not source.get("source_location"):
                claims.append({"memory_id":source.get("memory_id", "")})
                continue
            for location in source.get("source_location", []):
                claims.append({"memory_id": source["memory_id"], "version_id": source["version_id"],
                               "file_hash": source["file_hash"], "source_file": source["source_file"],
                               "location": location, "value": source["value"],
                               "field": source["claim_key"].rsplit(":", 1)[1]})
        return [self.verify(c, {s["memory_id"] for s in sources}) for c in claims]

    def answer(self, text, memories):
        """Explicit scalar citations only; the rest of a sentence stays unverified."""
        results = []
        for sentence in re.split(r"[。！？\n]+", text):
            if not sentence.strip():
                continue
            refs = [r for r in memories if r["type"] == "document" and re.search(r"(?<![A-Za-z0-9_.-])"+re.escape(Path(r["source_reference"]).name)+r"(?![A-Za-z0-9_.-])", sentence)]
            plain = sentence.replace("`", "").replace("*", "")
            locs = [m.group(0) for m in re.finditer(r"sheet\s+([^,，;；]+?)\s+cell\s+([A-Z]+\d+)|(?:page|paragraph|line|slide)\s+\d+\b", plain, re.I)]
            for match in re.finditer(r"第\s*(\d+)\s*(行|段(?:落)?|页|张幻灯片)", plain):
                label = {"行":"line", "段":"paragraph", "段落":"paragraph", "页":"page", "张幻灯片":"slide"}[match[2]]
                locs.append(label + " " + match[1])
            # Ranges, approximate references and multiple locations are ambiguous.
            ambiguous = bool(re.search(r"附近|左右|\d+\s*[-–—至]\s*\d+|(?:行|段|页)\s*(?:到|至)", plain))
            fields = []
            patterns = {
                "budget":r"(?:预算|budget)\s*(?:是|为|[:：])?\s*([\d,]+(?:\.\d+)?\s*(?:万元|万|元)?)(?![\d.])",
                "owner":r"(?:负责人|owner)\s*(?:是|为|[:：])\s*([^，,；;。()（）\s]{1,80})",
                "deadline":r"(?:截止日期|deadline)\s*(?:是|为|[:：])\s*([^，,；;。()（）]{1,80}?)(?=\s*(?:来自|来源)|[,，;；()（）]|$)",
            }
            for field, pattern in patterns.items():
                fields.extend((field, m[1].strip()) for m in re.finditer(pattern, plain, re.I))
            if len(refs) != 1 or len(locs) != 1 or not fields or ambiguous:
                results.append({"text": sentence, "status": "UNVERIFIED", "reason": "no_complete_explicit_scalar_citation", "evidence_class": "INFERRED"})
                continue
            row = refs[0]
            p = row["provenance"]
            for field, value in fields:
                claim = {"memory_id": row["id"], "version_id": p.get("version_id") or "",
                         "file_hash": p.get("file_hash") or "", "source_file": row["source_reference"],
                         "location": locs[0], "value": value, "field": field}
                results.append(self.verify(claim, {r["id"] for r in memories}) | {"text": sentence, "coverage":"explicit_scalar_only"})
            results.append({"text":sentence, "status":"UNVERIFIED", "reason":"remaining_sentence_semantics_not_verified", "evidence_class":"INFERRED"})
        return results
