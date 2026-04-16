"""TEI file I/O helpers — no spaCy dependency, safe to unit-test alone."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from .tokenizer import Language, Paragraph

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

ET.register_namespace("", TEI_NS)

PROLOG_PI_RE = re.compile(r"<\?xml-model[^?]*\?>", re.DOTALL)


def extract_xml_model_pi(source: str) -> Optional[str]:
    """Return the `<?xml-model ...?>` prolog PI verbatim, or None.

    ElementTree does not round-trip prolog processing instructions, so
    we grab the raw string and re-emit it ourselves in `write_tei`.
    """
    match = PROLOG_PI_RE.search(source)
    return match.group(0) if match else None


def detect_language(root: ET.Element) -> Optional[Language]:
    """Read `TEI/@xml:lang` and map to a `Language`, or return None."""
    lang = root.get(f"{{{XML_NS}}}lang")
    if not lang:
        return None
    lang = lang.strip().lower()
    if lang in {lang_enum.value for lang_enum in Language}:
        return Language(lang)
    return None


def extract_paragraphs(root: ET.Element) -> list[Paragraph]:
    """Collect every `<p xml:id="...">` under `<body>` as a `Paragraph`."""
    body = root.find(f".//{{{TEI_NS}}}body")
    if body is None:
        return []
    out: list[Paragraph] = []
    for p in body.iter(f"{{{TEI_NS}}}p"):
        pid = p.get(f"{{{XML_NS}}}id")
        if not pid:
            continue
        text = " ".join("".join(p.itertext()).split())
        if text:
            out.append(Paragraph(id=pid, text=text))
    return out


def _parse_tei_fragment(xml: str) -> ET.Element:
    """Parse a namespace-less TEI fragment by wrapping it in an xmlns root."""
    return ET.fromstring(f'<wrap xmlns="{TEI_NS}">{xml}</wrap>')


def replace_paragraphs(root: ET.Element, annotated: dict[str, str]) -> int:
    """Replace children of each matching `<p>` with tokenized `<w>`/`<pc>`.

    Returns the number of paragraphs replaced.
    """
    body = root.find(f".//{{{TEI_NS}}}body")
    if body is None:
        return 0
    replaced = 0
    for p in body.iter(f"{{{TEI_NS}}}p"):
        pid = p.get(f"{{{XML_NS}}}id")
        if not pid or pid not in annotated:
            continue
        new_p = _parse_tei_fragment(annotated[pid]).find(f"{{{TEI_NS}}}p")
        if new_p is None:
            continue
        for child in list(p):
            p.remove(child)
        p.text = None
        for child in list(new_p):
            p.append(child)
        replaced += 1
    return replaced


def insert_standoff(root: ET.Element, standoff_xml: str) -> None:
    """Append a fresh `<standOff>` to the TEI root, replacing any existing."""
    for existing in root.findall(f"{{{TEI_NS}}}standOff"):
        root.remove(existing)
    new_so = _parse_tei_fragment(standoff_xml).find(f"{{{TEI_NS}}}standOff")
    if new_so is not None:
        root.append(new_so)


def write_tei(
    tree: ET.ElementTree,
    path: Path,
    xml_model_pi: Optional[str] = None,
) -> None:
    """Serialize the tree, re-prepending the xml-model PI if present."""
    body = ET.tostring(tree.getroot(), encoding="unicode")
    header = '<?xml version="1.0" encoding="utf-8"?>\n'
    if xml_model_pi:
        header += xml_model_pi + "\n"
    path.write_text(header + body + "\n", encoding="utf-8")
