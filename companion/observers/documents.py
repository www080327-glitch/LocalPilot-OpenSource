"""Bounded, read-only extraction. Office files are ZIP/XML, never opened in Office."""
from dataclasses import dataclass, field
from io import BytesIO
import re
import posixpath
from xml.etree import ElementTree as ET
from zipfile import ZipFile


@dataclass
class Document:
    text: str
    structure: dict
    truncated: bool
    locations: list = field(default_factory=list)


def extractive_summary(document, max_chars=1200):
    lines = [line.strip() for line in document.text.splitlines() if line.strip()]
    return ("\n".join(lines))[:max_chars]


def extract(content, extension, max_chars=40000):
    structure = {"format": extension.lstrip(".")}
    if extension in {".txt", ".md"}:
        text = content.decode("utf-8", errors="replace")
    elif extension == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF skipped")
        if len(reader.pages) > 200:
            raise ValueError("PDF page budget exceeded")
        structure["pages"] = len(reader.pages)
        pages, size = [], 0
        for i, page in enumerate(reader.pages):
            value = f"[page {i+1}]\n" + (page.extract_text() or "")
            pages.append(value)
            size += len(value)
            if size > max_chars:
                break
        text = "\n".join(pages)
        if not text.strip() or not any((p.extract_text() or "").strip() for p in reader.pages[:1]):
            # No OCR guessing for scanned pages.
            structure["ocr"] = "NOT_RUN"
    else:
        with ZipFile(BytesIO(content)) as z:
            if len(z.infolist()) > 3000 or sum(x.file_size for x in z.infolist()) > 64*1024*1024:
                raise ValueError("Office archive expansion budget exceeded")
            def xml(name):
                data = z.read(name)
                if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
                    raise ValueError("XML entities refused")
                return ET.fromstring(data)
            def texts(tree, tag="t"):
                return [n.text or "" for n in tree.iter() if n.tag.rsplit("}", 1)[-1] == tag]
            def ordered_parts(main, relationships, tag, directory, fallback):
                if main not in z.namelist() or relationships not in z.namelist():
                    return [(name, "") for name in fallback]
                targets = {n.attrib["Id"]:n.attrib.get("Target", "") for n in xml(relationships)}
                result = []
                for node in xml(main).iter():
                    if node.tag.rsplit("}", 1)[-1] != tag:
                        continue
                    rid = node.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
                    target = targets.get(rid, "")
                    name = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(posixpath.dirname(main), target))
                    if not name.startswith(directory + "/") or name not in z.namelist():
                        raise ValueError("Invalid Office part relationship")
                    result.append((name, node.attrib.get("name", "")))
                return result
            if extension == ".docx":
                tree = xml("word/document.xml")
                paras = ["".join(texts(p)) for p in tree.iter() if p.tag.rsplit("}", 1)[-1] == "p"]
                structure["paragraphs"] = len(paras)
                text = "\n".join(paras)
            elif extension == ".pptx":
                names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=lambda n: int(re.search(r"(\d+)\.xml", n)[1]))
                names = [n for n, _ in ordered_parts("ppt/presentation.xml", "ppt/_rels/presentation.xml.rels", "sldId", "ppt/slides", names)]
                structure["slides"] = len(names)
                text = "\n".join(f"[slide {i+1}] " + " | ".join(texts(xml(n))) for i, n in enumerate(names))
            elif extension == ".xlsx":
                strings = ["".join(texts(si)) for si in xml("xl/sharedStrings.xml")] if "xl/sharedStrings.xml" in z.namelist() else []
                sheets = sorted((n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)), key=lambda n: int(re.search(r"(\d+)\.xml", n)[1]))
                ordered = ordered_parts("xl/workbook.xml", "xl/_rels/workbook.xml.rels", "sheet", "xl/worksheets", sheets)
                sheets, names = [n for n, _ in ordered], [label for _, label in ordered]
                structure.update(sheets=len(sheets), sheet_names=names, formulas="cached values only; not recalculated")
                rows = []
                for i, sheet in enumerate(sheets):
                    rows.append(f"[sheet {names[i] if i < len(names) else sheet}]")
                    for cell in xml(sheet).iter():
                        if cell.tag.rsplit("}", 1)[-1] != "c":
                            continue
                        values = texts(cell, "v")
                        value = values[0] if values else "".join(texts(cell))
                        if cell.attrib.get("t") == "s":
                            value = strings[int(value)]
                        formulas = texts(cell, "f")
                        rows.append(f"{cell.attrib.get('r','')}: {value}" + (f" [formula={formulas[0]}]" if formulas else ""))
                text = "\n".join(rows)
            else:
                raise ValueError("Unsupported document")
    bounded = text[:max_chars]
    # Locations refer to extracted text, not fabricated Office pagination.
    locations, offset, context = [], 0, ""
    for number, line in enumerate(bounded.splitlines(keepends=True), 1):
        marker = re.match(r"\[(page|slide|sheet) ([^\]]+)\]", line)
        if marker:
            context = marker.group(1) + " " + marker.group(2)
        if extension == ".md" and line.lstrip().startswith("#"):
            context = "section " + line.strip().lstrip("# ")
        if extension == ".docx":
            label = f"paragraph {number}"
        elif extension == ".xlsx":
            cell = re.match(r"([A-Z]+\d+):", line)
            label = context + (" cell " + cell.group(1) if cell else "")
        else:
            label = (context + "; " if context else "") + f"line {number}"
        if line.strip():
            locations.append({"location":label, "start":offset, "end":offset+len(line)})
        offset += len(line)
    if len(text) > max_chars and locations and not bounded.endswith(("\n", "\r")):
        # The cut may bisect a number, name or cell. Its prefix is not evidence.
        locations[-1]["incomplete"] = True
    return Document(bounded, structure, len(text) > max_chars, locations)
