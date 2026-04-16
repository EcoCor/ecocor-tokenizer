"""Extract inline entity annotations from a manually annotated vanilla TEI.

A human annotator marks tokens by wrapping their text content in a
category element:

    <w xml:id="eco_de_000033_90_1560"><Tier>Tiere</Tier></w>
    <w xml:id="eco_de_000033_110_2730"><Pflanze>Eichen</Pflanze></w>
    <w xml:id="eco_de_000033_110_3190"><Lebensraum>Feld</Lebensraum></w>

This module reads those inline markers and emits them as a stand-off
`<listAnnotation type="entities">` layer. The input file is not modified.

Usage:

    ecocor-extract-annotations ANNOTATED.xml -o ANNOTATIONS.xml
    ecocor-extract-annotations ANNOTATED.xml -o ANNOTATIONS.xml \\
        --layer-type ntee \\
        --resp-name "Mareike Schuhmacher" \\
        --app-ident tei_entity_enricher \\
        --app-url "https://github.com/NEISSproject/tei_entity_enricher"
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


def annotations_to_entity_layer(annotations: list[dict]) -> str:
    """Render extracted annotations as a `<listAnnotation type="entities">`."""
    if not annotations:
        return '<listAnnotation type="entities"/>'
    parts = ['<listAnnotation type="entities">']
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
            "emit them as a stand-off annotation layer."
        ),
    )
    parser.add_argument("input", type=Path, help="annotated TEI file")
    parser.add_argument(
        "-o", "--output", type=Path, required=True,
        help="output path for the annotation layer",
    )
    parser.add_argument(
        "--layer-type", default="ntee",
        help="layer type for xml:id suffix (default: ntee)",
    )
    parser.add_argument(
        "--resp-name", default="ntee",
        help="responsible person/tool name for respStmt",
    )
    parser.add_argument(
        "--resp-type", default="automated annotation",
        help="responsibility type (default: automated annotation)",
    )
    parser.add_argument(
        "--app-ident", default="",
        help="application identifier for appInfo (omit for purely manual)",
    )
    parser.add_argument(
        "--app-desc", default="",
        help="application label/description for appInfo",
    )
    parser.add_argument(
        "--app-url", default="",
        help="application URL (emitted as <ref> in appInfo)",
    )
    parser.add_argument(
        "--source-filename", default="",
        help="override the source filename in <ref type='source'> "
             "(default: derived from input filename)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    source_text = args.input.read_text(encoding="utf-8")
    tree = ET.ElementTree(ET.fromstring(source_text))
    root = tree.getroot()

    annotations = extract_inline_annotations(root)
    layer_xml = annotations_to_entity_layer(annotations)

    meta = extract_source_meta(root)
    source_filename = args.source_filename or args.input.name

    write_layer_tei(
        args.output,
        layer_xml,
        source_id=meta["id"],
        layer_type=args.layer_type,
        title=f"Entity annotations ({args.layer_type}): {meta['title'] or source_filename}",
        source_filename=source_filename,
        resp_name=args.resp_name,
        resp_type=args.resp_type,
        taxonomy_xml=ENTITY_TAXONOMY_WITH_HABITAT,
        app_ident=args.app_ident,
        app_version="",
        app_desc=args.app_desc or args.app_ident,
        app_url=args.app_url,
    )

    print(
        f"extracted {len(annotations)} annotation(s) -> {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
