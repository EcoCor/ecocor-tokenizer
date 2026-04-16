"""Export vanilla TEI + annotation layers as TSV.

Produces a tab-separated file with columns:

    token_id    paragraph_id    surface    lemma    [layer1    layer2    ...]

Reads token IDs, paragraph IDs, and surface forms from the vanilla TEI.
Lemmas come from the linguistic layer. Additional annotation layers
(entity, ntee, gold, ...) are added as extra columns.

Usage:

    ecocor-export-tsv VANILLA.xml -o OUTPUT.tsv \\
        --linguistic LINGUISTIC.xml \\
        --layer ntee:NTEE.xml \\
        --layer entity:ENTITY.xml \\
        --layer gold:GOLD.xml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from .tei import TEI_NS, XML_NS


def load_tokens(vanilla_path: Path) -> list[dict]:
    """Load all `<w>` and `<pc>` from the vanilla TEI with paragraph context."""
    tree = ET.parse(str(vanilla_path))
    root = tree.getroot()
    tokens: list[dict] = []

    for p in root.iter(f"{{{TEI_NS}}}p"):
        para_id = p.get(f"{{{XML_NS}}}id", "")
        for el in p:
            tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if tag not in ("w", "pc"):
                continue
            tid = el.get(f"{{{XML_NS}}}id", "")
            surface = (el.text or "").strip()
            tokens.append({
                "token_id": tid,
                "paragraph_id": para_id,
                "surface": surface,
                "type": tag,
            })

    return tokens


def load_lemmas(linguistic_path: Path) -> dict[str, str]:
    """Load token_id -> lemma mapping from a linguistic layer file."""
    tree = ET.parse(str(linguistic_path))
    root = tree.getroot()
    lemmas: dict[str, str] = {}

    for ann in root.iter(f"{{{TEI_NS}}}annotation"):
        target = ann.get("target", "")
        tid = target.lstrip("#").strip()
        note = ann.find(f"{{{TEI_NS}}}note[@type='lemma']")
        if note is None:
            note = ann.find("note[@type='lemma']")
        if tid and note is not None and note.text:
            lemmas[tid] = note.text.strip()

    return lemmas


def load_annotation_layer(layer_path: Path) -> dict[str, list[str]]:
    """Load an annotation layer, return token_id -> list of @ana values.

    A single token can have multiple annotations (e.g. from different
    entries in the word list). Values are collected into a list and
    joined with `|` on export.

    Handles both single-target and multi-target annotations:
        target="#tok1"           -> tok1 gets the ana value
        target="#tok1 #tok2"     -> both tok1 and tok2 get the ana value
    """
    tree = ET.parse(str(layer_path))
    root = tree.getroot()
    mapping: dict[str, list[str]] = {}

    for ann in root.iter(f"{{{TEI_NS}}}annotation"):
        target = ann.get("target", "")
        ana = ann.get("ana", "")
        # strip leading # from ana
        ana_clean = ana.lstrip("#")

        for ref in target.split():
            tid = ref.lstrip("#").strip()
            if tid and ana_clean:
                mapping.setdefault(tid, []).append(ana_clean)

    # also try without namespace (bare standOff files)
    for ann in root.iter("annotation"):
        target = ann.get("target", "")
        ana = ann.get("ana", "")
        ana_clean = ana.lstrip("#")
        for ref in target.split():
            tid = ref.lstrip("#").strip()
            if tid and ana_clean:
                mapping.setdefault(tid, []).append(ana_clean)

    return mapping


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecocor-export-tsv",
        description=(
            "Export vanilla TEI + annotation layers as TSV. "
            "Add layers with --layer NAME:FILE.xml (repeatable)."
        ),
    )
    parser.add_argument("input", type=Path, help="vanilla tokenized TEI")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="output TSV path (default: stdout)",
    )
    parser.add_argument(
        "--linguistic", type=Path, default=None,
        help="linguistic layer file (for lemma column)",
    )
    parser.add_argument(
        "--layer", action="append", default=[],
        metavar="NAME:FILE",
        help=(
            "add an annotation layer column. "
            "Format: NAME:PATH (e.g. ntee:annotations.xml). Repeatable."
        ),
    )
    return parser


def _parse_layer_arg(arg: str) -> tuple[str, Path]:
    if ":" not in arg:
        raise ValueError(
            f"invalid --layer format: '{arg}' (expected NAME:PATH)"
        )
    name, path_str = arg.split(":", 1)
    return name.strip(), Path(path_str.strip())


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    tokens = load_tokens(args.input)
    if not tokens:
        print("error: no <w>/<pc> tokens found", file=sys.stderr)
        return 2

    # Load lemmas
    lemmas: dict[str, str] = {}
    if args.linguistic:
        lemmas = load_lemmas(args.linguistic)
        print(
            f"loaded {len(lemmas)} lemma(s) from {args.linguistic}",
            file=sys.stderr,
        )

    # Load extra annotation layers
    layer_names: list[str] = []
    layer_data: list[dict[str, list[str]]] = []
    for layer_arg in args.layer:
        try:
            name, path = _parse_layer_arg(layer_arg)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        data = load_annotation_layer(path)
        layer_names.append(name)
        layer_data.append(data)
        print(
            f"loaded {len(data)} annotation(s) for layer '{name}' from {path}",
            file=sys.stderr,
        )

    # Build header
    header_parts = ["token_id", "paragraph_id", "surface", "lemma"]
    header_parts.extend(layer_names)
    header = "\t".join(header_parts)

    # Build rows
    rows: list[str] = [header]
    for t in tokens:
        lemma = lemmas.get(t["token_id"], "")
        parts = [t["token_id"], t["paragraph_id"], t["surface"], lemma]
        for ld in layer_data:
            values = ld.get(t["token_id"], [])
            parts.append("|".join(values))
        rows.append("\t".join(parts))

    output_text = "\n".join(rows) + "\n"

    if args.output:
        args.output.write_text(output_text, encoding="utf-8")
        print(
            f"exported {len(tokens)} token(s) -> {args.output}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(output_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
