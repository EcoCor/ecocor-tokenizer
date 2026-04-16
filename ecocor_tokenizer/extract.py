"""Extract inline entity annotations from a manually annotated vanilla TEI.

A human annotator marks tokens by wrapping their text content in a
category element:

    <w xml:id="eco_de_000033_90_1560"><Tier>Tiere</Tier></w>
    <w xml:id="eco_de_000033_110_2730"><Pflanze>Eichen</Pflanze></w>
    <w xml:id="eco_de_000033_110_3190"><Lebensraum>Feld</Lebensraum></w>

This module reads those inline markers and emits them as a stand-off
`<listAnnotation type="ntee">` layer. The input file is not modified.

Usage:

    ecocor-extract-annotations ANNOTATED.xml -o ANNOTATIONS.xml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as _xml_escape

from .tei import ENTITY_TAXONOMY_WITH_HABITAT, TEI_NS, XML_NS, extract_source_meta, write_layer_tei

CATEGORY_MAP: dict[str, str] = {
    "Tier": "cat-animal",
    "Pflanze": "cat-plant",
    "Lebensraum": "cat-habitat",
}


def _local_name(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _xml_attr(value: str) -> str:
    return _xml_escape(value, {'"': "&quot;"})


def extract_inline_annotations(root: ET.Element) -> list[dict]:
    """Walk the TEI, find annotated `<w>` elements, collect records.

    Each record: {token_id, category, surface}.
    """
    annotations: list[dict] = []
    for w in root.iter(f"{{{TEI_NS}}}w"):
        for child in list(w):
            local = _local_name(child.tag)
            if local not in CATEGORY_MAP:
                continue
            token_id = w.get(f"{{{XML_NS}}}id")
            if not token_id:
                continue
            annotations.append({
                "token_id": token_id,
                "category": CATEGORY_MAP[local],
                "surface": child.text or "",
            })
    return annotations


def annotations_to_ntee_layer(annotations: list[dict]) -> str:
    """Render extracted annotations as a `<listAnnotation type="ntee">`."""
    if not annotations:
        return '<listAnnotation type="ntee"/>'
    parts = ['<listAnnotation type="ntee">']
    for a in annotations:
        target = f"#{a['token_id']}"
        parts.append(
            f'  <annotation target="{_xml_attr(target)}" '
            f'ana="#{_xml_attr(a["category"])}"/>'
        )
    parts.append("</listAnnotation>")
    return "\n".join(parts)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecocor-extract-annotations",
        description=(
            "Extract inline entity annotations (<Tier>, <Pflanze>, "
            "<Lebensraum>) from a manually annotated vanilla TEI and "
            "emit them as a stand-off <listAnnotation type=\"ntee\"> layer."
        ),
    )
    parser.add_argument("input", type=Path, help="annotated TEI file")
    parser.add_argument(
        "-o", "--output", type=Path, required=True,
        help="output path for the annotation layer",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    source_text = args.input.read_text(encoding="utf-8")
    tree = ET.ElementTree(ET.fromstring(source_text))
    root = tree.getroot()

    annotations = extract_inline_annotations(root)
    layer_xml = annotations_to_ntee_layer(annotations)

    meta = extract_source_meta(root)
    source_filename = args.input.name

    write_layer_tei(
        args.output,
        layer_xml,
        source_id=meta["id"],
        layer_type="ntee",
        title=f"Manual entity annotations (ntee): {meta['title'] or source_filename}",
        source_filename=source_filename,
        resp_name="ntee",
        resp_type="manual annotation",
        taxonomy_xml=ENTITY_TAXONOMY_WITH_HABITAT,
    )

    print(
        f"extracted {len(annotations)} annotation(s) -> {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
