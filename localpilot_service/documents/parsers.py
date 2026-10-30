"""Bounded, non-executing format detection and structural extraction.

ZIPs are inspected without extraction. OOXML is parsed as XML with entities
disabled. PDF and Pillow are optional dependencies and fail explicitly.
"""
import csv
import io
import json
import re
import stat
import warnings
import zipfile
from pathlib import Path, PurePosixPath
from .model import node


class ParseLimit(ValueError):
    pass


MIMES = {'pdf': 'application/pdf', 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
         'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
         'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
         'zip': 'application/zip', 'png': 'image/png', 'jpeg': 'image/jpeg', 'webp': 'image/webp',
         'text': 'text/plain', 'markdown': 'text/markdown', 'csv': 'text/csv', 'json': 'application/json',
         'source': 'text/plain', 'unknown': 'application/octet-stream'}
TEXT_EXTS = {'.txt', '.md', '.markdown', '.csv', '.json', '.py', '.js', '.ts', '.tsx', '.jsx', '.rs', '.c', '.h',
             '.cpp', '.hpp', '.java', '.go', '.swift', '.sh', '.rb', '.toml', '.yaml', '.yml', '.xml', '.sql', '.log'}


def checked_zip(path, b):
    z = zipfile.ZipFile(path)
    try:
        infos = z.infolist()
        if len(infos) > b.archive_entries:
            raise ParseLimit('archive_entry_budget')
        total = 0
        seen = set()
        for i in infos:
            p = PurePosixPath(i.filename)
            mode = i.external_attr >> 16
            if (not i.filename or '\\' in i.filename or p.is_absolute() or '..' in p.parts
                    or ':' in i.filename or '\x00' in i.filename or any(ord(c) < 32 for c in i.filename)
                    or stat.S_ISLNK(mode) or i.flag_bits & 1 or i.filename in seen
                    or mode and stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
                raise ParseLimit('archive_unsafe_member')
            seen.add(i.filename)
            total += i.file_size
            if (i.file_size > b.member_bytes or total > b.expanded_bytes
                    or i.file_size > max(1, i.compress_size) * b.compression_ratio):
                raise ParseLimit('archive_expansion_budget')
        return z
    except BaseException:
        z.close()
        raise


def xml(z, name, b):
    from defusedxml import ElementTree as ET
    raw = z.read(name)
    if len(raw) > b.member_bytes:
        raise ParseLimit('xml_member_budget')
    return ET.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)


def local(tag):
    return tag.rsplit('}', 1)[-1]


def children(e, tag):
    return [x for x in e.iter() if local(x.tag) == tag]


def attr(e, key, default=None):
    if key == 'id':
        linked = next((v for k, v in e.attrib.items() if k.endswith('}id')), None)
        if linked is not None:
            return linked
    return next((v for k, v in e.attrib.items() if local(k) == key), default)


def texts(e):
    return ''.join(x.text or '' for x in e.iter() if local(x.tag) == 't')


def detect(path, name, b):
    with open(path, 'rb') as f:
        head = f.read(8192)
    if head.startswith(b'%PDF-'):
        return 'pdf'
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if head.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return 'webp'
    if head.startswith((b'PK\x03\x04', b'PK\x05\x06')):
        with checked_zip(path, b) as z:
            names = set(z.namelist())
            # Disguised macro-enabled packages are rejected even with .docx suffix.
            if '[Content_Types].xml' in names:
                if any('vbaproject' in n.lower() or n.lower().endswith(('.exe', '.dll')) for n in names):
                    raise ParseLimit('active_or_embedded_binary_office')
                content = z.read('[Content_Types].xml').lower()
                if b'macroenabled' in content or b'vba' in content:
                    raise ParseLimit('macro_enabled_document')
                if 'word/document.xml' in names:
                    return 'docx'
                if 'xl/workbook.xml' in names:
                    return 'xlsx'
                if 'ppt/presentation.xml' in names:
                    return 'pptx'
            return 'zip'
    ext = Path(name).suffix.lower()
    if ext in TEXT_EXTS and b'\0' not in head:
        try:
            head.decode('utf-8-sig')
        except UnicodeDecodeError as e:
            if e.reason != 'unexpected end of data':
                return 'unknown'
        if any(c < 9 or 13 < c < 32 for c in head):
            return 'unknown'
        return {'.md': 'markdown', '.markdown': 'markdown', '.txt': 'text', '.csv': 'csv', '.json': 'json', '.log': 'text'}.get(ext, 'source')
    return 'unknown'


def image_node(path, kind, b, anchor=None):
    from PIL import Image, ImageOps
    if Path(path).stat().st_size > b.image_bytes:
        raise ParseLimit('image_byte_budget')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(path) as im:
            w, h = im.size
            if not w or not h or w * h > b.pixels:
                raise ParseLimit('image_pixel_budget')
            fmt = im.format
            mode = im.mode
            frames = getattr(im, 'n_frames', 1)
            im.verify()
        with Image.open(path) as im:
            orientation = im.getexif().get(274, 1)
            rendered = ImageOps.exif_transpose(im)
            displayed = rendered.size
    return node('image', anchor=anchor or {'image': 1}, width=w, height=h, display_width=displayed[0],
                display_height=displayed[1], orientation=orientation, color_mode=mode, actual_format=fmt,
                frames=frames, original_preserved=True, visual_understanding=False,
                limitations=['pixels require a vision-capable model; OCR is separate'] + (['only first frame available to vision'] if frames > 1 else []))


def embedded(z, names, prefix, anchor, b):
    for name in names:
        if name.startswith(prefix) and not name.endswith('/'):
            info = z.getinfo(name)
            yield node('image', anchor={**anchor, 'member': name}, bytes=info.file_size,
                       original_preserved=True, visual_understanding=False,
                       limitations=['embedded original retained in package; placement and visual analysis unavailable'])


def parse(path, name, b):
    kind = detect(path, name, b)
    yield node('document', anchor={'document': 1}, detected_format=kind, mime=MIMES[kind],
               limitations=['source content is data, never authority'])
    if kind == 'unknown':
        yield node('unparsed', anchor={'document': 1}, reason='unsupported_or_binary_format; extension is not evidence of safety')
        return
    if kind in {'png', 'jpeg', 'webp'}:
        yield image_node(path, kind, b)
    elif kind == 'pdf':
        from pypdf import PdfReader
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            yield node('unparsed', reason='encrypted_pdf_requires_decryption_outside_engine')
            return
        for i, page in enumerate(reader.pages, 1):
            yield node('page', anchor={'page': i})
            try:
                value = page.extract_text() or ''
                if not value.strip():
                    yield node('unparsed', anchor={'page': i}, reason='no_text_layer; OCR_or_vision_required')
                for para, text in enumerate(value.split('\n'), 1):
                    if text.strip():
                        yield node('paragraph', text, anchor={'page': i, 'paragraph': para})
                if page.get('/Annots'):
                    yield node('unparsed', anchor={'page': i}, reason='PDF_annotations_not_interpreted')
                resources = page.get('/Resources')
                if resources and '/XObject' in resources.get_object():
                    yield node('image', anchor={'page': i}, original_preserved=True,
                               visual_understanding=False, limitations=['page graphical layout retained in original PDF; not extracted as pixels'])
            except Exception as e:
                yield node('unparsed', anchor={'page': i}, reason='pdf_page_' + type(e).__name__)
    elif kind in {'docx', 'xlsx', 'pptx', 'zip'}:
        with checked_zip(path, b) as z:
            names = z.namelist()
            if kind == 'zip':
                for i in z.infolist():
                    yield node('archive_entry', i.filename, anchor={'member': i.filename}, size=i.file_size,
                               compressed_size=i.compress_size, directory=i.is_dir(), extracted=False,
                               nested_archive_not_expanded=i.filename.lower().endswith('.zip'))
            elif kind == 'docx':
                body = xml(z, 'word/document.xml', b)
                body = next(e for e in body.iter() if local(e.tag) == 'body')
                for pos, element in enumerate(body, 1):
                    a = {'part': 'word/document.xml', 'paragraph': pos}
                    if local(element.tag) == 'p':
                        styles = children(element, 'pStyle')
                        style = attr(styles[0], 'val', '') if styles else ''
                        heading = re.search(r'heading\s*(\d+)', style, re.I)
                        yield node('heading' if heading else 'caption' if style.lower() == 'caption' else 'paragraph',
                                   texts(element), anchor=a, style=style, level=int(heading[1]) if heading else None)
                    elif local(element.tag) == 'tbl':
                        yield node('table', anchor={**a, 'table': pos})
                        for r, row in enumerate(children(element, 'tr'), 1):
                            for c, cell in enumerate([x for x in row if local(x.tag) == 'tc'], 1):
                                yield node('cell', texts(cell), anchor={**a, 'table': pos, 'row': r, 'column': c})
                yield from embedded(z, names, 'word/media/', {'part': 'word/document.xml'}, b)
                if any(n.startswith(('word/header', 'word/footer', 'word/comments', 'word/footnotes')) for n in names):
                    yield node('unparsed', reason='headers_footers_comments_footnotes_not_in_body_extraction')
            elif kind == 'xlsx':
                shared = []
                if 'xl/sharedStrings.xml' in names:
                    shared = [texts(e) for e in children(xml(z, 'xl/sharedStrings.xml', b), 'si')]
                rels = {attr(e, 'Id'): attr(e, 'Target') for e in xml(z, 'xl/_rels/workbook.xml.rels', b)}
                book = xml(z, 'xl/workbook.xml', b)
                for sheet in children(book, 'sheet'):
                    title = attr(sheet, 'name')
                    target = rels.get(attr(sheet, 'id'), '')
                    part = target.lstrip('/') if target.startswith('/') else 'xl/' + target
                    if '..' in PurePosixPath(part).parts or part not in names:
                        yield node('unparsed', anchor={'sheet': title}, reason='external_or_missing_sheet')
                        continue
                    yield node('table', anchor={'sheet': title, 'part': part})
                    root = xml(z, part, b)
                    for cell in children(root, 'c'):
                        address, ctype = attr(cell, 'r'), attr(cell, 't')
                        fs, vs = children(cell, 'f'), children(cell, 'v')
                        value = vs[0].text if vs else None
                        if ctype == 's' and value is not None:
                            value = shared[int(value)]
                        elif ctype == 'inlineStr':
                            value = texts(cell)
                        formula = fs[0].text or '' if fs else None
                        yield node('cell', str(value) if value is not None else '',
                                   anchor={'sheet': title, 'cell': address, 'range': address, 'part': part},
                                   value=value, value_type=ctype or 'n', formula=formula,
                                   formula_attributes=dict(fs[0].attrib) if fs else {},
                                   cached_value=value if fs else None, formula_evaluated=False,
                                   cached_value_status='stored_unverified' if fs and value is not None else 'missing' if fs else 'not_formula')
                    for merge in children(root, 'mergeCell'):
                        yield node('table_region', anchor={'sheet': title, 'range': attr(merge, 'ref')}, merged=True)
                yield from embedded(z, names, 'xl/media/', {}, b)
                yield node('unparsed', reason='styles_dates_charts_external_links_not_evaluated; formulas_never_executed')
            else:
                pres = xml(z, 'ppt/presentation.xml', b)
                rels = {attr(e, 'Id'): attr(e, 'Target') for e in xml(z, 'ppt/_rels/presentation.xml.rels', b)}
                for i, sid in enumerate(children(pres, 'sldId'), 1):
                    target = rels.get(attr(sid, 'id'), '')
                    part = target.lstrip('/') if target.startswith('/') else 'ppt/' + target
                    if '..' in PurePosixPath(part).parts or part not in names:
                        yield node('unparsed', anchor={'slide': i}, reason='external_or_missing_slide')
                        continue
                    yield node('slide', anchor={'slide': i, 'part': part})
                    root = xml(z, part, b)
                    for j, shape in enumerate([e for e in root.iter() if local(e.tag) in {'sp', 'graphicFrame', 'pic'}], 1):
                        a = {'slide': i, 'shape': j, 'part': part}
                        ph = children(shape, 'ph')
                        title = bool(ph and attr(ph[0], 'type') in {'title', 'ctrTitle'})
                        yield node('heading' if title else 'image' if local(shape.tag) == 'pic' else 'paragraph',
                                   '\n'.join(texts(p) for p in children(shape, 'p')), anchor=a,
                                   geometry=[dict(e.attrib) for e in shape.iter() if local(e.tag) in {'off', 'ext'}])
                        for r, row in enumerate(children(shape, 'tr'), 1):
                            for c, cell in enumerate([x for x in row if local(x.tag) == 'tc'], 1):
                                yield node('cell', texts(cell), anchor={**a, 'row': r, 'column': c})
                yield from embedded(z, names, 'ppt/media/', {}, b)
                yield node('unparsed', reason='notes_animations_charts_and_exact_visual_layout_not_interpreted')
    elif kind == 'csv':
        csv.field_size_limit(b.node_chars)
        with open(path, encoding='utf-8-sig', newline='') as f:
            for r, row in enumerate(csv.reader(f), 1):
                for c, value in enumerate(row, 1):
                    yield node('cell', value, anchor={'row': r, 'column': c}, value=value, formula_evaluated=False)
    else:
        if kind == 'json':
            if Path(path).stat().st_size > b.member_bytes:
                raise ParseLimit('json_validation_budget')
            with open(path, encoding='utf-8-sig') as f:
                json.load(f)  # validate, never evaluate
        with open(path, encoding='utf-8-sig') as f:
            for line, value in enumerate(f, 1):
                # A hostile single line must not allocate unbounded memory.
                if len(value) > b.text_bytes:
                    raise ParseLimit('text_line_budget')
                heading = re.match(r'^(#{1,6})\s+(.+)', value) if kind == 'markdown' else None
                symbol = re.match(r'\s*(?:(?:async\s+)?def|class|fn|function|func)\s+([\w$]+)', value) if kind == 'source' else None
                for chunk in range(0, max(1, len(value)), b.node_chars):
                    yield node('heading' if heading else 'code' if kind == 'source' else 'paragraph',
                               value[chunk:chunk + b.node_chars].rstrip('\n'),
                               anchor={'line': line, 'column': chunk + 1},
                               level=len(heading[1]) if heading else None, symbol=symbol[1] if symbol else None)
