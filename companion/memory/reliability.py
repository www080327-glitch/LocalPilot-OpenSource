"""Conservative explicit field conflicts. No model guesses become observations."""
import re
from pathlib import Path

CLASSES = {"factual":"OBSERVED", "inferred":"INFERRED", "reflection":"REFLECTION"}


def scalar(value):
    text = re.sub(r"\s+", "", str(value)).strip("。；; ").replace(",", "")
    match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)(万|万元|元)?", text)
    if match:
        from decimal import Decimal
        return ("number", Decimal(match[1]) * (10000 if match[2] in {"万", "万元"} else 1))
    return ("text", text)


def scalar_locations(meta, field, value):
    text = meta.get("index_text", "")
    out = []
    labels = {"budget":{"预算", "budget"}, "owner":{"负责人", "owner"}, "deadline":{"截止日期", "deadline"}}
    for loc in meta.get("locations", []):
        if loc.get("incomplete"):
            continue
        fragment = text[loc["start"]:loc["end"]].strip()
        if meta.get("structure", {}).get("format") == "xlsx":
            match = re.fullmatch(r"sheet (.+) cell ([A-Z]+)(\d+)", loc["location"])
            if not match:
                continue
            sheet, col, row = match.groups()
            sheet_body = next((part.split("\n", 1)[1] for part in re.split(r"\[sheet ", text)[1:] if part.startswith(sheet + "]\n")), "")
            header = any(int(number) < int(row) and v.strip().lower() in labels[field]
                         for number, v in re.findall(r"^" + re.escape(col) + r"(\d+): (.*)$", sheet_body, re.M))
            actual = re.sub(r"^[A-Z]+\d+:\s*", "", fragment).split(" [formula=", 1)[0]
            supported = header and scalar(actual) == scalar(value)
        else:
            supported = any(key.endswith(":" + field) and scalar(actual) == scalar(value)
                            for key, actual in explicit_claims(fragment, "source.txt"))
        if supported:
            out.append(loc["location"])
    return out


def explicit_claims(text, reference):
    """Only labelled scalar fields; this is not a general semantic fact checker."""
    project = re.search(r"(?:项目|project)\s*[:：]\s*([^\n；;]+)", text, re.I)
    scope = project.group(1).strip() if project else Path(reference).parent.name
    for label, key in (("预算|budget", "budget"), ("负责人|owner", "owner"), ("截止日期|deadline", "deadline")):
        for match in re.finditer(r"(?:" + label + r")\s*[:：]\s*([^\n；;。|]+)", text, re.I):
            yield scope + ":" + key, match.group(1).strip()
    if Path(reference).suffix.lower() == ".xlsx":
        # Explicit table headers and their same-column values are direct source data.
        # Formula strings without a cached value are never substituted for a value.
        for sheet in re.split(r"\[sheet [^\]]+\]", text)[1:]:
            cells = {}
            for col, row, value in re.findall(r"^([A-Z]+)(\d+): (.*)$", sheet, re.M):
                cells[(col,int(row))] = value.split(" [formula=",1)[0].strip()
            labels = {"预算":"budget", "budget":"budget", "负责人":"owner", "owner":"owner", "截止日期":"deadline", "deadline":"deadline"}
            headers = [(col,row,labels[value.lower()]) for (col,row),value in cells.items() if value.lower() in labels]
            project_headers = [(col,row) for (col,row),value in cells.items() if value.lower() in {"项目", "project"}]
            for col, header_row, key in headers:
                for (value_col,value_row), value in cells.items():
                    if value_col != col or value_row <= header_row or not value or value.lower() in labels:
                        continue
                    row_scope = next((cells.get((pcol,value_row)) for pcol,prow in project_headers if prow == header_row and cells.get((pcol,value_row))), scope)
                    yield row_scope + ":" + key, value


def provenance(row, tokens=()):
    meta = row["metadata"]
    text = meta.get("index_text", row["summary"])
    locations = meta.get("locations", [])
    if meta.get("matched_windows"):
        locations = [loc for loc in locations if any(loc["end"] > start and loc["start"] < end for start, end in meta["matched_windows"])]
    hits = [loc["location"] for loc in locations if any(t in text[loc["start"]:loc["end"]].lower() for t in tokens)]
    return {"source_file":row["source_reference"], "file_hash":meta.get("sha256"),
            "version_id":meta.get("version_id"), "extraction_timestamp":meta.get("extraction_timestamp"),
            "document_type":meta.get("structure", {}).get("format"), "source_location":hits[:6] or [l["location"] for l in locations[:2]],
            "derived_summary":row["summary"], "evidence_class":CLASSES[row["epistemic"]],
            "confidence":row["confidence"], "summary_method":meta.get("summary_method", row["source"])}
