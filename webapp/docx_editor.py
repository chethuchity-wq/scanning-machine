"""
Edit a Word report in the browser.

The .docx stays the single source of truth: `render` turns it into HTML in
which every paragraph is editable, and `save` writes the edited text back
into the *same* paragraphs, so tables, fonts, bullets, letterhead margin,
images and footer are untouched. Only text and bold/italic/underline are
editable - enough for reporting, and it keeps the printout identical to
what the clinic's template produces.

Paragraphs are addressed by their position ("pid") in a fixed walk of the
document: body order, descending into table cells row by row. `version` (the
file's modification time) guards against the walk changing underneath an
open editor, e.g. if the report was also edited in Word meanwhile.
"""

from __future__ import annotations

import base64
import copy
import html
from html.parser import HTMLParser
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

EMU_PER_INCH = 914400
TWIPS_PER_INCH = 1440


class VersionConflict(Exception):
    """The file changed since it was opened in the editor."""


def version_of(path: str | Path) -> str:
    return str(Path(path).stat().st_mtime_ns)


# ---------------------------------------------------------------------------
# Walking the document
# ---------------------------------------------------------------------------

def _walk_paragraphs(container):
    """Every w:p in document order, descending into table cells."""
    for child in container.iterchildren():
        if child.tag == qn("w:p"):
            yield child
        elif child.tag == qn("w:tbl"):
            for tr in child.iterchildren(qn("w:tr")):
                for tc in tr.iterchildren(qn("w:tc")):
                    yield from _walk_paragraphs(tc)


def _paragraph_index(body) -> dict:
    return {p: i for i, p in enumerate(_walk_paragraphs(body))}


def _has_drawing(p) -> bool:
    return bool(p.findall(".//" + qn("w:drawing")))


def _is_page_break(p) -> bool:
    return any(br.get(qn("w:type")) == "page" for br in p.iter(qn("w:br")))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_ALIGN_CLASS = {
    WD_ALIGN_PARAGRAPH.CENTER: "al-center",
    WD_ALIGN_PARAGRAPH.RIGHT: "al-right",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "al-justify",
}


def _run_html(run: Run) -> str:
    out = []
    for child in run._r.iterchildren():
        if child.tag == qn("w:t"):
            out.append(html.escape(child.text or ""))
        elif child.tag == qn("w:br") and child.get(qn("w:type")) != "page":
            out.append("<br>")
        elif child.tag == qn("w:tab"):
            out.append("&emsp;")
    text = "".join(out)
    if not text:
        return ""
    if run.underline:
        text = f"<u>{text}</u>"
    if run.italic:
        text = f"<i>{text}</i>"
    if run.bold:
        text = f"<b>{text}</b>"
    return text


def _paragraph_size(paragraph: Paragraph, default_pt: float) -> float:
    for run in paragraph.runs:
        if run.font.size:
            return run.font.size.pt
    style_size = paragraph.style.font.size if paragraph.style is not None else None
    return style_size.pt if style_size else default_pt


def _image_html(doc, p) -> str:
    imgs = []
    for drawing in p.iter(qn("w:drawing")):
        blip = drawing.find(".//" + qn("a:blip"))
        extent = drawing.find(".//" + qn("wp:extent"))
        if blip is None:
            continue
        part = doc.part.related_parts.get(blip.get(qn("r:embed")))
        if part is None:
            continue
        width = int(extent.get("cx")) / EMU_PER_INCH if extent is not None else 3
        data = base64.b64encode(part.blob).decode()
        imgs.append(f'<img src="data:{part.content_type};base64,{data}" style="width:{width:.2f}in">')
    return "".join(imgs)


def _render_paragraph(doc, p, pid: int, default_pt: float) -> str:
    if _has_drawing(p):
        return f'<div class="dp-img" contenteditable="false">{_image_html(doc, p)}</div>'
    if _is_page_break(p):
        return '<div class="page-break" contenteditable="false" title="Page break"></div>'
    paragraph = Paragraph(p, doc._body)
    classes = ["dp"]
    align = paragraph.alignment
    if align is None and paragraph.style is not None:
        align = paragraph.style.paragraph_format.alignment
    if align in _ALIGN_CLASS:
        classes.append(_ALIGN_CLASS[align])
    if paragraph.style is not None and paragraph.style.name.startswith("List Bullet"):
        classes.append("bullet")
    if paragraph.paragraph_format.keep_with_next:
        classes.append("kwn")  # page markers keep it with what follows, as Word does
    size = _paragraph_size(paragraph, default_pt)
    before, after = _spacing(paragraph)
    inner = "".join(_run_html(r) for r in paragraph.runs)
    return (f'<p class="{" ".join(classes)}" data-pid="{pid}" '
            f'style="font-size:{size:g}pt;margin:{before:g}pt 0 {after:g}pt">{inner}</p>')


def _spacing(paragraph: Paragraph) -> tuple[float, float]:
    """Space before/after in points: the paragraph's own, else its style's."""
    def pick(attr):
        for fmt in (paragraph.paragraph_format, paragraph.style.paragraph_format if paragraph.style else None):
            value = getattr(fmt, attr, None) if fmt is not None else None
            if value is not None:
                return value.pt
        return 0.0
    return pick("space_before"), pick("space_after")


def _render_table(doc, tbl, index, default_pt) -> str:
    style = tbl.find(qn("w:tblPr") + "/" + qn("w:tblStyle"))
    grid = style is not None and style.get(qn("w:val")) == "TableGrid"
    cols = [int(c.get(qn("w:w"), 0)) / TWIPS_PER_INCH
            for c in tbl.findall(qn("w:tblGrid") + "/" + qn("w:gridCol"))]
    # A table whose rows keep with the next stays on one page (see build_templates)
    first_row = tbl.find(qn("w:tr"))
    keep = first_row is not None and first_row.find(".//" + qn("w:keepNext")) is not None
    out = [f'<table class="dt{" grid" if grid else ""}{" keep" if keep else ""}"><colgroup>']
    out += [f'<col style="width:{w:.2f}in">' for w in cols]
    out.append("</colgroup>")
    for tr in tbl.iterchildren(qn("w:tr")):
        out.append("<tr>")
        for tc in tr.iterchildren(qn("w:tc")):
            span = tc.find(qn("w:tcPr") + "/" + qn("w:gridSpan"))
            colspan = f' colspan="{span.get(qn("w:val"))}"' if span is not None else ""
            valign = tc.find(qn("w:tcPr") + "/" + qn("w:vAlign"))
            va = {"center": "middle", "bottom": "bottom"}.get(valign.get(qn("w:val")) if valign is not None else "", "top")
            out.append(f'<td{colspan} style="vertical-align:{va}">{_render_blocks(doc, tc, index, default_pt)}</td>')
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def _render_blocks(doc, container, index, default_pt) -> str:
    out = []
    for child in container.iterchildren():
        if child.tag == qn("w:p"):
            out.append(_render_paragraph(doc, child, index[child], default_pt))
        elif child.tag == qn("w:tbl"):
            out.append(_render_table(doc, child, index, default_pt))
    return "".join(out)


def render(path: str | Path) -> dict:
    """HTML of the report for the editor, plus the page geometry and version."""
    doc = Document(str(path))
    body = doc.element.body
    normal = doc.styles["Normal"].font.size
    default_pt = normal.pt if normal else 11
    section = doc.sections[0]
    return {
        "html": _render_blocks(doc, body, _paragraph_index(body), default_pt),
        "version": version_of(path),
        "page": {
            "width": section.page_width.inches,
            "height": section.page_height.inches,
            "top": section.top_margin.inches,
            "bottom": section.bottom_margin.inches,
            "left": section.left_margin.inches,
            "right": section.right_margin.inches,
        },
    }


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

class _Segments(HTMLParser):
    """Editor HTML -> [(text, bold, italic, underline)], "\n" for a line break."""

    _TAGS = {"b": "b", "strong": "b", "i": "i", "em": "i", "u": "u"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.segments: list[tuple[str, bool, bool, bool]] = []

    def _flags(self):
        return ("b" in self.stack, "i" in self.stack, "u" in self.stack)

    def handle_starttag(self, tag, attrs):
        if tag in self._TAGS:
            self.stack.append(self._TAGS[tag])
        elif tag == "br":
            self.segments.append(("\n", False, False, False))

    def handle_endtag(self, tag):
        mark = self._TAGS.get(tag)
        if mark and mark in self.stack:
            # remove the innermost occurrence
            del self.stack[len(self.stack) - 1 - self.stack[::-1].index(mark)]

    def handle_data(self, data):
        if data:
            self.segments.append((data.replace("\xa0", " ").replace(" ", " "), *self._flags()))


def _segments(fragment: str) -> list[tuple[str, bool, bool, bool]]:
    parser = _Segments()
    parser.feed(fragment or "")
    parser.close()
    segs = parser.segments
    # Browsers leave a trailing <br> in edited blocks
    while segs and segs[-1][0] == "\n":
        segs.pop()
    # Merge neighbours with the same formatting
    merged: list[tuple[str, bool, bool, bool]] = []
    for seg in segs:
        if merged and seg[0] != "\n" and merged[-1][0] != "\n" and merged[-1][1:] == seg[1:]:
            merged[-1] = (merged[-1][0] + seg[0], *seg[1:])
        else:
            merged.append(seg)
    return merged


def _current_segments(doc, p) -> list:
    paragraph = Paragraph(p, doc._body)
    return _segments("".join(_run_html(r) for r in paragraph.runs))


def _write_segments(doc, p, segments) -> None:
    """Replace the paragraph's runs, keeping the first run's font."""
    runs = p.findall(qn("w:r"))
    base_rpr = None
    if runs and runs[0].find(qn("w:rPr")) is not None:
        base_rpr = copy.deepcopy(runs[0].find(qn("w:rPr")))
    for r in runs:
        p.remove(r)
    paragraph = Paragraph(p, doc._body)
    for text, bold, italic, underline in segments:
        r = OxmlElement("w:r")
        if base_rpr is not None:
            r.append(copy.deepcopy(base_rpr))
        p.append(r)
        run = Run(r, paragraph)
        if text == "\n":
            run.add_break()
            continue
        run.text = text
        run.bold = bold
        run.italic = italic
        run.underline = underline


def save(path: str | Path, version: str, blocks: list[dict]) -> str:
    """
    Apply the editor's paragraphs to the .docx and return the new version.

    `blocks` lists every editable paragraph currently in the editor, in order:
    {"pid": int} for an existing paragraph or {"pid": null} for one added
    after the previous block ({"before": pid} when it opens a table cell),
    each with its "html". Existing paragraphs that are missing were deleted.
    """
    path = Path(path)
    if not blocks:
        raise ValueError("Nothing to save")
    if version_of(path) != version:
        raise VersionConflict()
    doc = Document(str(path))
    by_pid = {i: p for i, p in enumerate(_walk_paragraphs(doc.element.body))}

    seen = set()
    anchor = None
    for block in blocks:
        pid = block.get("pid")
        segments = _segments(block.get("html", ""))
        before = block.get("before")
        # Splitting a paragraph in the browser copies its pid; the second copy is new
        if pid is not None and int(pid) in by_pid and int(pid) not in seen:
            p = by_pid[int(pid)]
            seen.add(int(pid))
            if segments != _current_segments(doc, p):
                _write_segments(doc, p, segments)
            anchor = p
        elif before is not None and int(before) in by_pid:
            # New paragraph opening a table cell: goes before the cell's first one
            target = by_pid[int(before)]
            new = copy.deepcopy(target)
            target.addprevious(new)
            _write_segments(doc, new, segments)
            anchor = new
        elif anchor is not None:
            # New paragraph: same style as the one it follows (bullet stays bullet)
            new = copy.deepcopy(anchor)
            anchor.addnext(new)
            _write_segments(doc, new, segments)
            anchor = new

    for pid, p in by_pid.items():
        if pid in seen or _has_drawing(p) or _is_page_break(p):
            continue
        parent = p.getparent()
        # A table cell must keep a paragraph; clear it instead
        if parent.tag == qn("w:tc") and len(parent.findall(qn("w:p"))) == 1:
            _write_segments(doc, p, [])
        else:
            parent.remove(p)

    doc.save(str(path))
    return version_of(path)
