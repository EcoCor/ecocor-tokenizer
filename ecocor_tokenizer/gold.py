"""Extract gold standard annotations and align them to tokenized text.

Gold standard files are TEI with raw text in `<body>` (no `<p>`, no
`<w>`) and inline annotation wrappers:

    ...running text <Tier>Tiere</Tier> more text <Pflanze>Eichen</Pflanze>...

Two modes:

1. **Self-tokenize** (no `--align-to`): tokenize the gold text with
   spaCy, align annotations to the new tokens, emit a vanilla TEI +
   gold layer.

2. **Align to existing vanilla** (`--align-to VANILLA.xml`): match
   the gold text to existing `<w>` tokens by greedy surface-form
   alignment. Emit only the gold layer with `@target` pointing at the
   existing vanilla token IDs. No new tokenization file produced.

Usage:

    # self-tokenize
    ecocor-extract-gold GOLD.xml -o TOKENIZED.xml --gold-out LAYER.xml --language de

    # align to existing vanilla
    ecocor-extract-gold GOLD.xml --align-to VANILLA.xml --gold-out LAYER.xml --language de
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as _xml_escape

from .tokenizer import Language, linguistic_layer
from .tei import (
    ENTITY_TAXONOMY_WITH_HABITAT,
    STTS_TAXONOMY,
    TEI_NS,
    XML_NS,
    extract_source_meta,
    extract_xml_model_pi,
    write_layer_tei,
    write_tei,
)

ET.register_namespace("", TEI_NS)

CATEGORY_MAP: dict[str, str] = {
    "Tier": "cat-animal",
    "Pflanze": "cat-plant",
    "Lebensraum": "cat-habitat",
}

SENTENCE_END_CHARS = {".", "!", "?"}


def _local_name(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _xml_attr(value: str) -> str:
    return _xml_escape(value, {'"': "&quot;"})


def _gold_token_id(para_id: str, position: int) -> str:
    return f"{para_id}_{position:07d}"


# ---- text + annotation extraction from gold files -----------------------


def collect_text_and_annotations(body: ET.Element) -> tuple[str, list[dict]]:
    """Walk body, concatenate plain text, record annotation char spans."""
    parts: list[str] = []
    annotations: list[dict] = []

    def _walk(el: ET.Element) -> None:
        local = _local_name(el.tag)
        is_ann = local in CATEGORY_MAP

        if is_ann:
            start = sum(len(p) for p in parts)

        if el.text:
            parts.append(el.text)

        for child in el:
            _walk(child)
            if child.tail:
                parts.append(child.tail)

        if is_ann:
            end = sum(len(p) for p in parts)
            annotations.append({
                "start": start,
                "end": end,
                "category": CATEGORY_MAP[local],
            })

    _walk(body)
    text = "".join(parts)
    for ann in annotations:
        ann["surface"] = text[ann["start"]:ann["end"]]
    return text, annotations


# ---- mode 1: self-tokenize ----------------------------------------------


def tokenize_with_charmap(nlp, text: str, para_id: str) -> list[dict]:
    """Tokenize text with spaCy, return records including char offsets."""
    doc = nlp(text)

    sentence_end_idx: set[int] = set()
    for sent in doc.sents:
        last = None
        for tok in sent:
            if not tok.is_space:
                last = tok
        if last is not None and last.is_punct and last.text in SENTENCE_END_CHARS:
            sentence_end_idx.add(last.i)

    records: list[dict] = []
    position = 10
    for tok in doc:
        if tok.is_space:
            continue
        records.append({
            "id": _gold_token_id(para_id, position),
            "surface": tok.text,
            "lemma": tok.lemma_,
            "pos": tok.tag_,
            "is_punct": tok.is_punct,
            "sentence_end": tok.i in sentence_end_idx,
            "char_start": tok.idx,
            "char_end": tok.idx + len(tok.text),
        })
        position += 10
    return records


def align_annotations_by_charspan(
    annotations: list[dict], tokens: list[dict]
) -> list[dict]:
    """Map char-span annotations to overlapping token IDs."""
    mapped: list[dict] = []
    for ann in annotations:
        matching = [
            t["id"]
            for t in tokens
            if t["char_start"] < ann["end"]
            and t["char_end"] > ann["start"]
            and not t["is_punct"]
        ]
        if matching:
            mapped.append({
                "token_ids": matching,
                "category": ann["category"],
                "surface": ann["surface"],
            })
    return mapped


def tokens_to_vanilla_tei(para_id: str, tokens: list[dict]) -> str:
    parts = [f'<p xml:id="{_xml_attr(para_id)}">']
    for t in tokens:
        surface = _xml_escape(t["surface"])
        if t["is_punct"]:
            unit = ' unit="sentence"' if t.get("sentence_end") else ""
            parts.append(
                f'  <pc{unit} xml:id="{_xml_attr(t["id"])}">{surface}</pc>'
            )
        else:
            parts.append(
                f'  <w xml:id="{_xml_attr(t["id"])}">{surface}</w>'
            )
    parts.append("</p>")
    return "\n".join(parts)


# ---- mode 2: align to existing vanilla ----------------------------------


def load_vanilla_tokens(vanilla_path: Path) -> list[dict]:
    """Load all `<w>` elements from an existing vanilla tokenized TEI."""
    tree = ET.parse(str(vanilla_path))
    root = tree.getroot()
    tokens: list[dict] = []
    for w in root.iter(f"{{{TEI_NS}}}w"):
        tid = w.get(f"{{{XML_NS}}}id")
        surface = (w.text or "").strip()
        if tid and surface:
            tokens.append({"id": tid, "surface": surface})
    return tokens


def _matches_ahead(
    gold_tokens: list[dict],
    gi: int,
    vanilla_tokens: list[dict],
    vj: int,
    need: int = 3,
) -> bool:
    """Check if `need` consecutive non-punct gold tokens starting at gi
    match vanilla tokens starting at vj. Used to confirm that a
    candidate alignment point is real, not a coincidental heading match.
    """
    got = 0
    gii, vjj = gi, vj
    while got < need and gii < len(gold_tokens) and vjj < len(vanilla_tokens):
        while gii < len(gold_tokens) and gold_tokens[gii]["is_punct"]:
            gii += 1
        if gii >= len(gold_tokens):
            break
        if vanilla_tokens[vjj]["surface"] == gold_tokens[gii]["surface"]:
            got += 1
            gii += 1
            vjj += 1
        else:
            return False
    return got >= need


def align_gold_to_vanilla(
    annotations: list[dict],
    gold_text: str,
    vanilla_tokens: list[dict],
    nlp,
) -> tuple[list[dict], int, int]:
    """Align gold annotation spans to existing vanilla token IDs.

    Uses a two-phase greedy alignment:
    1. **Seek phase**: scan for a candidate match confirmed by 3+
       consecutive matching tokens (prevents heading words from
       accidentally matching body text at wrong positions).
    2. **Run phase**: once confirmed, do fast 1:1 greedy matching with
       a small lookahead (10 tokens) for minor tokenization differences.
       When the run breaks, fall back to seek phase.
    """
    doc = nlp(gold_text)
    gold_tokens: list[dict] = []
    for tok in doc:
        if tok.is_space:
            continue
        gold_tokens.append({
            "surface": tok.text,
            "char_start": tok.idx,
            "char_end": tok.idx + len(tok.text),
            "is_punct": tok.is_punct,
        })

    # Map annotations → gold token indices
    ann_gold_indices: list[list[int]] = []
    for ann in annotations:
        matching = [
            i
            for i, gt in enumerate(gold_tokens)
            if gt["char_start"] < ann["end"]
            and gt["char_end"] > ann["start"]
            and not gt["is_punct"]
        ]
        ann_gold_indices.append(matching)

    # Two-phase alignment
    SEEK_LOOKAHEAD = 500
    RUN_LOOKAHEAD = 10
    CONFIRM = 3
    gold_to_vanilla: dict[int, int] = {}
    vi = 0
    matched = 0
    total_words = sum(1 for gt in gold_tokens if not gt["is_punct"])
    gi = 0

    while gi < len(gold_tokens):
        gt = gold_tokens[gi]
        if gt["is_punct"]:
            gi += 1
            continue

        # ---- seek phase: find a confirmed alignment point ----
        limit = min(vi + SEEK_LOOKAHEAD, len(vanilla_tokens))
        found = False
        for vj in range(vi, limit):
            if vanilla_tokens[vj]["surface"] == gt["surface"]:
                if _matches_ahead(gold_tokens, gi, vanilla_tokens, vj, CONFIRM):
                    gold_to_vanilla[gi] = vj
                    vi = vj + 1
                    matched += 1
                    gi += 1
                    found = True
                    break

        if not found:
            gi += 1
            continue

        # ---- run phase: fast greedy 1:1 matching ----
        while gi < len(gold_tokens):
            gt = gold_tokens[gi]
            if gt["is_punct"]:
                gi += 1
                continue

            if vi < len(vanilla_tokens) and vanilla_tokens[vi]["surface"] == gt["surface"]:
                gold_to_vanilla[gi] = vi
                vi += 1
                matched += 1
                gi += 1
            else:
                # small lookahead for minor misalignments
                small_found = False
                for vj in range(vi, min(vi + RUN_LOOKAHEAD, len(vanilla_tokens))):
                    if vanilla_tokens[vj]["surface"] == gt["surface"]:
                        gold_to_vanilla[gi] = vj
                        vi = vj + 1
                        matched += 1
                        gi += 1
                        small_found = True
                        break
                if not small_found:
                    break  # lost sync → back to seek phase

    # Map annotations to vanilla token IDs via the alignment
    mapped: list[dict] = []
    unmatched = 0
    for ann, gold_indices in zip(annotations, ann_gold_indices):
        vanilla_ids = []
        for gi_ref in gold_indices:
            if gi_ref in gold_to_vanilla:
                vanilla_ids.append(
                    vanilla_tokens[gold_to_vanilla[gi_ref]]["id"]
                )
        if vanilla_ids:
            mapped.append({
                "token_ids": vanilla_ids,
                "category": ann["category"],
                "surface": ann["surface"],
            })
        else:
            unmatched += 1

    if unmatched:
        print(
            f"warning: {unmatched} annotation(s) could not be aligned",
            file=sys.stderr,
        )

    return mapped, matched, total_words


# ---- stand-off rendering ------------------------------------------------


def gold_layer_to_standoff(mapped: list[dict]) -> str:
    if not mapped:
        return '<listAnnotation type="gold"/>'
    parts = ['<listAnnotation type="gold">']
    for a in mapped:
        targets = " ".join(f"#{tid}" for tid in a["token_ids"])
        parts.append(
            f'  <annotation target="{_xml_attr(targets)}" '
            f'ana="#{_xml_attr(a["category"])}"/>'
        )
    parts.append("</listAnnotation>")
    return "\n".join(parts)


# ---- helpers -------------------------------------------------------------


def _derive_doc_id(path: Path) -> str:
    name = path.stem
    name = re.sub(r"^(Goldstandard_|Testtext_)", "", name)
    name = re.sub(r"_gold\d*$", "", name)
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    return f"gold_{name.lower()}"


# ---- CLI -----------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ecocor-extract-gold",
        description=(
            "Extract inline gold annotations and align them to "
            "tokenized text."
        ),
    )
    parser.add_argument("input", type=Path, help="gold standard TEI file")
    parser.add_argument(
        "--gold-out", type=Path, required=True,
        help="output path for the gold annotation layer",
    )
    parser.add_argument(
        "--align-to", type=Path, default=None,
        help=(
            "existing vanilla tokenized TEI to align to. "
            "If omitted, the gold text is self-tokenized and -o is required."
        ),
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="output tokenized vanilla TEI (only in self-tokenize mode)",
    )
    parser.add_argument(
        "--linguistic-out", type=Path, default=None,
        help="emit linguistic layer (only in self-tokenize mode)",
    )
    parser.add_argument(
        "--language", choices=[l.value for l in Language], required=True,
        help="language (gold files have no @xml:lang)",
    )
    parser.add_argument(
        "--doc-id", default=None,
        help="document ID for token IDs in self-tokenize mode "
             "(default: derived from filename)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    source_text = args.input.read_text(encoding="utf-8")
    tree = ET.ElementTree(ET.fromstring(source_text))
    root = tree.getroot()
    body = root.find(f".//{{{TEI_NS}}}body")

    if body is None:
        print("error: no <body> found", file=sys.stderr)
        return 2

    language = Language(args.language)
    nlp = language.get_spacy_model()

    # Extract plain text + annotation char spans
    plain_text, annotations = collect_text_and_annotations(body)
    print(
        f"extracted {len(annotations)} inline annotation(s) "
        f"({len(plain_text)} chars)",
        file=sys.stderr,
    )

    if args.align_to:
        # ---- mode 2: align to existing vanilla ----
        vanilla_tokens = load_vanilla_tokens(args.align_to)
        print(
            f"loaded {len(vanilla_tokens)} <w> tokens from {args.align_to}",
            file=sys.stderr,
        )

        mapped, matched, total = align_gold_to_vanilla(
            annotations, plain_text, vanilla_tokens, nlp
        )
        print(
            f"aligned {matched}/{total} gold words to vanilla tokens "
            f"({matched * 100 // max(total, 1)}%)",
            file=sys.stderr,
        )
        print(
            f"mapped {len(mapped)}/{len(annotations)} annotation(s)",
            file=sys.stderr,
        )

        gold_xml = gold_layer_to_standoff(mapped)
        # For align mode, get source metadata from the vanilla file
        vanilla_tree = ET.parse(str(args.align_to))
        vanilla_meta = extract_source_meta(vanilla_tree.getroot())
        write_layer_tei(
            args.gold_out,
            gold_xml,
            source_id=vanilla_meta["id"],
            layer_type="gold",
            title=f"Gold standard annotations: {vanilla_meta['title'] or args.align_to.name}",
            source_filename=args.align_to.name,
            resp_name="FFH project team",
            resp_type="gold standard annotation",
            taxonomy_xml=ENTITY_TAXONOMY_WITH_HABITAT,
        )
        print(f"gold layer -> {args.gold_out}", file=sys.stderr)

    else:
        # ---- mode 1: self-tokenize ----
        if not args.output:
            print(
                "error: -o/--output required in self-tokenize mode "
                "(or use --align-to)",
                file=sys.stderr,
            )
            return 2

        doc_id = args.doc_id or _derive_doc_id(args.input)
        para_id = f"{doc_id}_10"

        tokens = tokenize_with_charmap(nlp, plain_text, para_id)
        print(f"tokenized into {len(tokens)} token(s)", file=sys.stderr)

        mapped = align_annotations_by_charspan(annotations, tokens)
        print(f"aligned {len(mapped)} annotation(s) to tokens", file=sys.stderr)

        # Build tokenized vanilla TEI
        xml_model_pi = extract_xml_model_pi(source_text)
        vanilla_p = tokens_to_vanilla_tei(para_id, tokens)
        for child in list(body):
            body.remove(child)
        body.text = None
        new_p = ET.fromstring(
            f'<wrap xmlns="{TEI_NS}">{vanilla_p}</wrap>'
        ).find(f"{{{TEI_NS}}}p")
        if new_p is not None:
            body.append(new_p)

        write_tei(tree, args.output, xml_model_pi)
        print(f"vanilla TEI -> {args.output}", file=sys.stderr)

        # Gold layer
        gold_xml = gold_layer_to_standoff(mapped)
        write_layer_tei(
            args.gold_out,
            gold_xml,
            source_id=doc_id,
            layer_type="gold",
            title=f"Gold standard annotations: {args.input.name}",
            source_filename=args.output.name,
            resp_name="FFH project team",
            resp_type="gold standard annotation",
            taxonomy_xml=ENTITY_TAXONOMY_WITH_HABITAT,
        )
        print(f"gold layer -> {args.gold_out}", file=sys.stderr)

        # Optional linguistic layer
        if args.linguistic_out:
            ling_xml = linguistic_layer([tokens], language)
            write_layer_tei(
                args.linguistic_out,
                ling_xml,
                source_id=doc_id,
                layer_type="linguistic",
                title=f"Linguistic annotations: {args.input.name}",
                source_filename=args.output.name,
                resp_name="ecocor-tokenizer",
                taxonomy_xml=STTS_TAXONOMY,
                app_ident="ecocor-tokenizer",
                app_version="0.1.0",
                app_desc=f"spaCy {language.value}_core_news_sm",
            )
            print(f"linguistic layer -> {args.linguistic_out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
