"""Command-line interface for the EcoCor tokenizer.

Run:

    ecocor-tokenize IN.xml -o OUT.xml

Both stand-off layers (linguistic + entity) are appended inside one
`<standOff>` in the output TEI. To route a layer to its own file, pass
`--linguistic-out` and/or `--entity-out` — each layer omitted stays
inline, each set is written to the given path as a self-contained TEI
`<standOff>` document.

    ecocor-tokenize IN.xml -o OUT.xml \\
        --linguistic-out OUT.linguistic.xml \\
        --entity-out OUT.entity.xml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from .tei import (
    ENTITY_TAXONOMY,
    STTS_TAXONOMY,
    TEI_NS,
    detect_language,
    extract_paragraphs,
    extract_source_meta,
    extract_xml_model_pi,
    insert_standoff,
    mark_as_tokenized,
    prepare_tokenized_header,
    replace_paragraphs,
    write_layer_tei,
    write_tei,
)
from .tokenizer import (
    AnnotateRequest,
    Language,
    UrlDescriptor,
    annotate,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecocor-tokenize",
        description=(
            "Tokenize a TEI document into vanilla <w>/<pc> and emit "
            "stand-off linguistic + entity annotations."
        ),
    )
    parser.add_argument("input", type=Path, help="input TEI file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="output path for the tokenized TEI",
    )
    parser.add_argument(
        "--linguistic-out",
        type=Path,
        default=None,
        help="write the linguistic layer to its own file instead of inlining it",
    )
    parser.add_argument(
        "--entity-out",
        type=Path,
        default=None,
        help="write the entity layer to its own file instead of inlining it",
    )
    parser.add_argument(
        "--language",
        choices=[lang.value for lang in Language],
        default=None,
        help="override language (default: read TEI/@xml:lang)",
    )
    parser.add_argument(
        "--entity-list",
        default=None,
        help="override the word-list URL (default: language's built-in list)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    source_text = args.input.read_text(encoding="utf-8")
    xml_model_pi = extract_xml_model_pi(source_text)

    tree = ET.ElementTree(ET.fromstring(source_text))
    root = tree.getroot()

    language = (
        Language(args.language) if args.language else detect_language(root)
    )
    if language is None:
        print(
            "error: could not detect language from TEI/@xml:lang; "
            "pass --language de|en",
            file=sys.stderr,
        )
        return 2

    paragraphs = extract_paragraphs(root)
    if not paragraphs:
        print(
            "error: no <p xml:id=...> elements found in <body>",
            file=sys.stderr,
        )
        return 2

    request = AnnotateRequest(
        paragraphs=paragraphs,
        language=language,
        entity_list=(
            UrlDescriptor(url=args.entity_list) if args.entity_list else None
        ),
    )
    response = annotate(request)

    annotated = {p.id: p.xml for p in response.paragraphs}
    replaced = replace_paragraphs(root, annotated)

    # Source metadata for layer headers (before modifying the root)
    meta = extract_source_meta(root)
    source_filename = args.input.name

    # Mark vanilla TEI: type="tokenized", xml:id → {id}_tokenized
    tokenized_id = mark_as_tokenized(root)
    prepare_tokenized_header(root)

    # Each layer either goes to its own file (split) or gets inlined
    # inside a combined <standOff> appended to the base TEI.
    inline_layers: list[str] = []

    if args.linguistic_out:
        write_layer_tei(
            args.linguistic_out,
            response.linguistic,
            source_id=meta["id"],
            layer_type="linguistic",
            title=f"Linguistic annotations: {meta['title'] or source_filename}",
            source_filename=source_filename,
            resp_name="ecocor-tokenizer",
            taxonomy_xml=STTS_TAXONOMY,
            app_ident="ecocor-tokenizer",
            app_version="0.1.0",
            app_desc=f"spaCy {language.value}_core_news_sm",
        )
    else:
        inline_layers.append(response.linguistic)

    if args.entity_out:
        write_layer_tei(
            args.entity_out,
            response.entity,
            source_id=meta["id"],
            layer_type="dictionarylookup",
            title=f"Dictionary lookup annotations: {meta['title'] or source_filename}",
            source_filename=source_filename,
            resp_name="ecocor-tokenizer",
            taxonomy_xml=ENTITY_TAXONOMY,
            app_ident="ecocor-tokenizer",
            app_version="0.1.0",
            app_desc="Word list: animal_plant-{}.json".format(language.value),
        )
    else:
        inline_layers.append(response.entity)

    if inline_layers:
        combined = (
            "<standOff>\n" + "\n".join(inline_layers) + "\n</standOff>"
        )
        insert_standoff(root, combined)

    # Don't emit the xml-model PI (ELTeC schema no longer applies)
    write_tei(tree, args.output)

    print(
        f"tokenized {replaced} paragraph(s) -> {args.output}",
        file=sys.stderr,
    )
    if args.linguistic_out:
        print(f"linguistic layer -> {args.linguistic_out}", file=sys.stderr)
    if args.entity_out:
        print(f"entity layer -> {args.entity_out}", file=sys.stderr)

    return 0
