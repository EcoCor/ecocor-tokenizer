"""Tests for the pure (non-spaCy) helpers.

Exercises token id formatting, vanilla TEI emission, entity matching,
and stand-off layer rendering (linguistic + entity) without loading
any NLP model.
"""

from xml.etree import ElementTree as ET

from ecocor_tokenizer.tokenizer import (
    Language,
    entity_layer,
    linguistic_layer,
    match_entities,
    paragraph_to_tei,
    token_id,
)

TEI_NS = "http://www.tei-c.org/ns/1.0"
XMLNS = "http://www.w3.org/XML/1998/namespace"


def _wrap(xml: str) -> ET.Element:
    return ET.fromstring(f'<wrap xmlns="{TEI_NS}">{xml}</wrap>')


# ---- ids & TEI fragments ------------------------------------------------


def test_token_id_zero_pads_to_four_digits_step_ten():
    assert token_id("eco_de_000033_30", 10) == "eco_de_000033_30_0010"
    assert token_id("eco_de_000033_30", 1570) == "eco_de_000033_30_1570"


def test_paragraph_to_tei_is_vanilla_no_lemma_no_pos():
    tokens = [
        {"id": "p1_0010", "surface": "Hallo", "lemma": "hallo",
         "pos": "ITJ", "is_punct": False, "sentence_end": False},
        {"id": "p1_0020", "surface": ".", "lemma": ".",
         "pos": "$.", "is_punct": True, "sentence_end": True},
    ]
    xml = paragraph_to_tei("p1", tokens)
    root = _wrap(xml)

    w = root.find(f".//{{{TEI_NS}}}w")
    assert w is not None
    assert w.get("lemma") is None, "w must not carry @lemma in vanilla TEI"
    assert w.get("pos") is None, "w must not carry @pos in vanilla TEI"
    assert w.get(f"{{{XMLNS}}}id") == "p1_0010"
    assert w.text == "Hallo"

    pc = root.find(f".//{{{TEI_NS}}}pc")
    assert pc is not None
    assert pc.get("unit") == "sentence"
    assert pc.get(f"{{{XMLNS}}}id") == "p1_0020"


def test_paragraph_to_tei_escapes_special_chars():
    tokens = [{"id": "p1_0010", "surface": "A&B", "lemma": "A&B",
               "pos": "NN", "is_punct": False, "sentence_end": False}]
    xml = paragraph_to_tei("p1", tokens)
    assert "A&amp;B" in xml


# ---- entity layer -------------------------------------------------------


def test_match_entities_fans_out_multiple_ids_per_lemma():
    tokens = [[
        {"id": "p1_0010", "surface": "Chow-Chow", "lemma": "Chow-Chow",
         "pos": "NN", "is_punct": False, "sentence_end": False},
    ]]
    index = {"Chow-Chow": [
        {"name": "Chow-Chow", "wikidata_id": "Q1",
         "category": "Animal", "additional_wikidata_ids": []},
        {"name": "Chow-Chow", "wikidata_id": "Q2",
         "category": "Animal", "additional_wikidata_ids": []},
    ]}
    anns = match_entities(tokens, index)
    assert [a["wikidata_id"] for a in anns] == ["Q1", "Q2"]
    assert all(a["token_id"] == "p1_0010" for a in anns)


def test_match_entities_skips_punct():
    tokens = [[{"id": "p1_0010", "surface": ".", "lemma": ".",
                "pos": "$.", "is_punct": True, "sentence_end": True}]]
    assert match_entities(tokens, {".": [{
        "name": ".", "wikidata_id": "Q0", "category": "Animal",
        "additional_wikidata_ids": [],
    }]}) == []


def test_entity_layer_minimal_annotation_shape():
    anns = [{"token_id": "p1_0010", "category": "Plant",
             "wikidata_id": "Q106094", "name": "Granatapfelbaum"}]
    xml = entity_layer(anns)
    root = _wrap(xml)
    la = root.find(f".//{{{TEI_NS}}}listAnnotation")
    assert la is not None
    assert la.get("type") == "entities"
    ann = la.find(f"{{{TEI_NS}}}annotation")
    assert ann is not None
    assert ann.get("target") == "#p1_0010"
    assert ann.get("ana") == "#cat-plant"
    assert ann.get("corresp") == "https://www.wikidata.org/wiki/Q106094"


def test_entity_layer_empty_is_self_closed():
    assert entity_layer([]) == '<listAnnotation type="entities"/>'


# ---- linguistic layer ---------------------------------------------------


def test_linguistic_layer_emits_pos_via_ana_and_lemma_via_note():
    tokens = [[
        {"id": "p1_0010", "surface": "Königreichs", "lemma": "Königreich",
         "pos": "NN", "is_punct": False, "sentence_end": False},
        {"id": "p1_0020", "surface": ".", "lemma": ".",
         "pos": "$.", "is_punct": True, "sentence_end": True},
    ]]
    xml = linguistic_layer(tokens, Language.DE)
    root = _wrap(xml)

    la = root.find(f".//{{{TEI_NS}}}listAnnotation")
    assert la is not None
    assert la.get("type") == "linguistic"

    anns = la.findall(f"{{{TEI_NS}}}annotation")
    assert len(anns) == 1, "punct tokens must be skipped"
    ann = anns[0]
    assert ann.get("target") == "#p1_0010"
    assert ann.get("ana") == "#stts-NN"
    note = ann.find(f"{{{TEI_NS}}}note")
    assert note is not None
    assert note.get("type") == "lemma"
    assert note.text == "Königreich"


def test_linguistic_layer_uses_ptb_prefix_for_english():
    tokens = [[{"id": "p1_0010", "surface": "King", "lemma": "king",
                "pos": "NN", "is_punct": False, "sentence_end": False}]]
    xml = linguistic_layer(tokens, Language.EN)
    assert 'ana="#ptb-NN"' in xml


def test_linguistic_layer_empty_when_only_punct():
    tokens = [[{"id": "p1_0010", "surface": ".", "lemma": ".",
                "pos": "$.", "is_punct": True, "sentence_end": True}]]
    xml = linguistic_layer(tokens, Language.DE)
    assert xml == '<listAnnotation type="linguistic"/>'
