"""Core tokenization + annotation pipeline.

Base TEI output is *vanilla* — only `<w xml:id="...">` and
`<pc xml:id="..."[ unit="sentence"])` with no linguistic attributes.
Linguistic features (POS + lemma) and entity classifications live in
two separate stand-off layers, shaped as `<listAnnotation>` blocks.

Pure logic (id scheme, TEI fragment emission, entity matching, layer
rendering) stays free of spaCy so it can be unit-tested without the
models. Only `tokenize_paragraph` and `annotate` load spaCy.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from functools import cache
from typing import Optional
from xml.sax.saxutils import escape as _xml_escape

import requests
import spacy
from pydantic import BaseModel
from pydantic.networks import HttpUrl

SENTENCE_END_CHARS = {".", "!", "?"}

DEFAULT_ENTITY_LISTS = {
    "de": "https://raw.githubusercontent.com/EcoCor/ecocor-extractor/main/word_list/german/animal_plant-de.json",
    "en": "https://raw.githubusercontent.com/EcoCor/ecocor-extractor/main/word_list/english/animal_plant-en.json",
}

# @ana pointers in the linguistic layer use a tagset prefix so POS tags
# from different languages don't collide ("NN" means different things
# in STTS vs. Penn Treebank).
POS_TAGSET_PREFIX = {
    "de": "stts",
    "en": "ptb",
}


# ---- enums & models -----------------------------------------------------


class Language(str, Enum):
    EN = "en"
    DE = "de"

    @cache
    def get_spacy_model(self) -> spacy.Language:
        return {
            Language.DE: lambda: spacy.load("de_core_news_sm"),
            Language.EN: lambda: spacy.load("en_core_web_sm"),
        }[self]()

    def default_entity_list(self) -> str:
        return DEFAULT_ENTITY_LISTS[self.value]

    def pos_tagset_prefix(self) -> str:
        return POS_TAGSET_PREFIX[self.value]


class UrlDescriptor(BaseModel):
    url: HttpUrl


class Paragraph(BaseModel):
    """A source TEI `<p>` identified by xml:id, content as plain text."""
    id: str
    text: str


class ParagraphXml(BaseModel):
    id: str
    xml: str


class EntityInfo(BaseModel):
    name: str
    wikidata_id: str
    category: str
    additional_wikidata_ids: list[str] = []


class EntityListMetadata(BaseModel):
    name: str
    description: str
    date: date


class EntityListPayload(BaseModel):
    metadata: EntityListMetadata
    entity_list: list[EntityInfo]


class AnnotateRequest(BaseModel):
    paragraphs: list[Paragraph]
    language: Language
    entity_list: Optional[UrlDescriptor] = None

    def resolved_entity_list_url(self) -> str:
        if self.entity_list:
            return str(self.entity_list.url)
        return self.language.default_entity_list()


class AnnotateResponse(BaseModel):
    """Result of `annotate()`.

    `linguistic` and `entity` are each a `<listAnnotation>` fragment
    (no `<standOff>` wrapper). The caller composes them into a file or
    inlines them into the source TEI.
    """
    metadata: EntityListMetadata
    paragraphs: list[ParagraphXml]
    linguistic: str
    entity: str


# ---- pure helpers (no spaCy) --------------------------------------------


def _xml_attr(value: str) -> str:
    return _xml_escape(value, {'"': "&quot;"})


def token_id(paragraph_id: str, position: int) -> str:
    """Stable per-paragraph token id: `{paragraph-id}_{NNNN}`, step 10."""
    return f"{paragraph_id}_{position:04d}"


def paragraph_to_tei(paragraph_id: str, tokens: list[dict]) -> str:
    """Render token records into a vanilla `<p>` TEI fragment.

    `<w>` and `<pc>` carry only `xml:id` (plus `@unit="sentence"` on
    sentence-final punctuation). Lemma and POS live in the linguistic
    stand-off layer, not here.
    """
    parts = [f'<p xml:id="{_xml_attr(paragraph_id)}">']
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


def match_entities(
    tokens_by_paragraph: list[list[dict]],
    entity_index: dict[str, list[dict]],
) -> list[dict]:
    """Find tokens whose lemma matches a word-list entry.

    Returns one record per (token, word-list entry) pair — the same
    lemma can carry multiple wikidata ids, which we fan out.
    """
    annotations = []
    for tokens in tokens_by_paragraph:
        for tok in tokens:
            if tok["is_punct"]:
                continue
            for entry in entity_index.get(tok["lemma"], []):
                annotations.append(
                    {
                        "token_id": tok["id"],
                        "category": entry["category"],
                        "wikidata_id": entry["wikidata_id"],
                        "name": entry["name"],
                    }
                )
    return annotations


def entity_layer(annotations: list[dict]) -> str:
    """Render entity records into a `<listAnnotation type="entity">` block."""
    if not annotations:
        return '<listAnnotation type="entity"/>'
    parts = ['<listAnnotation type="entity">']
    for a in annotations:
        cat_id = f"cat-{a['category'].lower()}"
        target = f"#{a['token_id']}"
        parts.append(
            f'  <annotation target="{_xml_attr(target)}" '
            f'ana="#{_xml_attr(cat_id)}" '
            f'corresp="https://www.wikidata.org/wiki/{_xml_attr(a["wikidata_id"])}"/>'
        )
    parts.append("</listAnnotation>")
    return "\n".join(parts)


def linguistic_layer(
    tokens_by_paragraph: list[list[dict]],
    language: Language,
) -> str:
    """Render a `<listAnnotation type="linguistic">` block for every non-punct token.

    Each annotation carries POS via `@ana` (pointer into the language's
    POS taxonomy, e.g. `#stts-NN`) and lemma via `<note type="lemma">`.
    """
    tagset = language.pos_tagset_prefix()
    lines = ['<listAnnotation type="linguistic">']
    emitted = False
    for tokens in tokens_by_paragraph:
        for t in tokens:
            if t["is_punct"]:
                continue
            target = f"#{t['id']}"
            pos = t["pos"]
            lemma = _xml_escape(t["lemma"])
            lines.append(
                f'  <annotation target="{_xml_attr(target)}" '
                f'ana="#{tagset}-{_xml_attr(pos)}">'
                f'<note type="lemma">{lemma}</note></annotation>'
            )
            emitted = True
    if not emitted:
        return f'<listAnnotation type="linguistic"/>'
    lines.append("</listAnnotation>")
    return "\n".join(lines)


# ---- spaCy-backed functions ---------------------------------------------


def tokenize_paragraph(
    nlp: spacy.Language, paragraph: Paragraph
) -> list[dict]:
    """Run spaCy on a paragraph, return flat token records.

    Record shape: `{id, surface, lemma, pos, is_punct, sentence_end}`.
    `pos` is `token.tag_` — STTS for `de_core_news_*`, Penn Treebank for
    `en_core_web_*`.
    """
    doc = nlp(paragraph.text)

    sentence_end_idx = set()
    for sent in doc.sents:
        last = None
        for tok in sent:
            if not tok.is_space:
                last = tok
        if last is not None and last.is_punct and last.text in SENTENCE_END_CHARS:
            sentence_end_idx.add(last.i)

    records = []
    position = 10
    for tok in doc:
        if tok.is_space:
            continue
        records.append(
            {
                "id": token_id(paragraph.id, position),
                "surface": tok.text,
                "lemma": tok.lemma_,
                "pos": tok.tag_,
                "is_punct": tok.is_punct,
                "sentence_end": tok.i in sentence_end_idx,
            }
        )
        position += 10
    return records


def load_entity_list(url: str) -> EntityListPayload:
    response = requests.get(url)
    response.raise_for_status()
    return EntityListPayload(**response.json())


def annotate(request: AnnotateRequest) -> AnnotateResponse:
    """End-to-end: tokenize, render vanilla TEI, build both layers."""
    nlp = request.language.get_spacy_model()
    entity_payload = load_entity_list(request.resolved_entity_list_url())

    entity_index: dict[str, list[dict]] = {}
    for entry in entity_payload.entity_list:
        entity_index.setdefault(entry.name, []).append(entry.model_dump())

    paragraphs_out: list[ParagraphXml] = []
    all_tokens: list[list[dict]] = []

    for paragraph in request.paragraphs:
        tokens = tokenize_paragraph(nlp, paragraph)
        paragraphs_out.append(
            ParagraphXml(id=paragraph.id, xml=paragraph_to_tei(paragraph.id, tokens))
        )
        all_tokens.append(tokens)

    linguistic_xml = linguistic_layer(all_tokens, request.language)
    entity_annotations = match_entities(all_tokens, entity_index)
    entity_xml = entity_layer(entity_annotations)

    return AnnotateResponse(
        metadata=entity_payload.metadata,
        paragraphs=paragraphs_out,
        linguistic=linguistic_xml,
        entity=entity_xml,
    )
