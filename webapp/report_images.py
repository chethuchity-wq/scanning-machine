"""
Which scan images are in a Word report, and adding or removing one.

The report's images sit at its end, on their own page under the
"ULTRASOUND IMAGES" heading (fill_report._add_images_section). Each picture
carries the name of its scan image ("image_03.jpg" in scan_data) as its
description. Reports made before that have unnamed pictures; those are
matched to the scan images by comparing small greyscale thumbnails.

Adding or removing an image rebuilds that section from the scan images, in
the order they were taken, so the grid stays tidy.
"""

from __future__ import annotations

import io
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from PIL import Image, ImageChops, ImageStat

import fill_report

_THUMB = (32, 24)
# Mean grey-level difference (0-255) under which two thumbnails are the same
# image - a scan JPEG against the report's PNG of it differs by about 1
_SAME_IMAGE = 8.0


def _thumb(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data)).convert("L").resize(_THUMB)


def _difference(a: Image.Image, b: Image.Image) -> float:
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def _section_start(body):
    """The page-break paragraph opening the images section, or None."""
    children = list(body.iterchildren())
    for i, child in enumerate(children):
        if child.tag == qn("w:p") and "".join(t.text or "" for t in child.iter(qn("w:t"))).strip() == fill_report.IMAGES_HEADING:
            prev = children[i - 1] if i else None
            if prev is not None and prev.tag == qn("w:p") and any(
                    br.get(qn("w:type")) == "page" for br in prev.iter(qn("w:br"))):
                return prev
            return child
    return None


def _section_pictures(doc) -> list[tuple[str, bytes]]:
    """(stored name or "", image bytes) of each picture in the images section, in order."""
    start = _section_start(doc.element.body)
    if start is None:
        return []
    pictures = []
    node = start
    while node is not None:
        if node.tag != qn("w:sectPr"):
            for drawing in node.iter(qn("w:drawing")):
                doc_pr = drawing.find(".//" + qn("wp:docPr"))
                blip = drawing.find(".//" + qn("a:blip"))
                part = doc.part.related_parts.get(blip.get(qn("r:embed"))) if blip is not None else None
                if part is not None:
                    pictures.append(((doc_pr.get("descr") or "") if doc_pr is not None else "", part.blob))
        node = node.getnext()
    return pictures


def _scan_files(scan_dir: Path) -> list[str]:
    return sorted(p.name for p in scan_dir.glob("image_*.jpg"))


def _match(pictures, scan_dir: Path) -> list[str | None]:
    """Each picture's scan image name: its stored name, else the closest-looking scan image."""
    files = _scan_files(scan_dir)
    names: list[str | None] = [n if n in files else None for n, _ in pictures]
    unmatched = [f for f in files if f not in names]
    if None in names and unmatched:
        thumbs = {f: _thumb((scan_dir / f).read_bytes()) for f in unmatched}
        for i, (_, blob) in enumerate(pictures):
            if names[i] is not None or not thumbs:
                continue
            try:
                pic = _thumb(blob)
            except Exception:
                continue
            best = min(thumbs, key=lambda f: _difference(pic, thumbs[f]))
            if _difference(pic, thumbs[best]) <= _SAME_IMAGE:
                names[i] = best
                del thumbs[best]
    return names


def images_in_report(docx_path: str | Path, scan_dir: Path) -> list[str]:
    """Names of the scan images that are in the report."""
    doc = Document(str(docx_path))
    return [n for n in _match(_section_pictures(doc), scan_dir) if n]


def set_image(docx_path: str | Path, scan_dir: Path, name: str, include: bool) -> list[str]:
    """Add (include=True) or remove one scan image; returns the images now in the report."""
    if name not in _scan_files(scan_dir):
        raise ValueError(f"No scan image {name}")
    doc = Document(str(docx_path))
    pictures = _section_pictures(doc)
    names = _match(pictures, scan_dir)
    # Pictures that match no scan image are kept, after the scan images
    others = [blob for n, (_, blob) in zip(names, pictures) if n is None]
    wanted = {n for n in names if n}
    if include:
        wanted.add(name)
    else:
        wanted.discard(name)

    # Rebuild the section: drop the old one, append the new grid at the end
    start = _section_start(doc.element.body)
    if start is not None:
        node = start
        while node is not None and node.tag != qn("w:sectPr"):
            following = node.getnext()
            node.getparent().remove(node)
            node = following
    images = [(n, (scan_dir / n).read_bytes()) for n in sorted(wanted)] + others
    fill_report._add_images_section(doc, images)
    doc.save(str(docx_path))
    return sorted(wanted)
