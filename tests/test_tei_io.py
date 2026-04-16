"""Tests for the TEI file-I/O layer (still no spaCy dependency)."""

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from ecocor_tokenizer.tei import (
    detect_language,
    extract_paragraphs,
    extract_xml_model_pi,
    insert_standoff,
    replace_paragraphs,
    write_tei,
)
from ecocor_tokenizer.tokenizer import Language

SAMPLE_TEI = """\
<?xml version="1.0" encoding="utf-8"?>
<?xml-model href="https://example.org/schema.rng" type="application/xml"?>
<TEI xml:id="doc1" xml:lang="de" xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc><titleStmt><title>x</title></titleStmt>
    <publicationStmt><p>x</p></publicationStmt>
    <sourceDesc><p>x</p></sourceDesc></fileDesc></teiHeader>
  <text><body>
    <p xml:id="p1">Erste Sätze hier.</p>
    <p xml:id="p2">Zweiter Satz.</p>
  </body></text>
</TEI>
"""


def test_extract_xml_model_pi_returns_verbatim():
    pi = extract_xml_model_pi(SAMPLE_TEI)
    assert pi is not None
    assert 'href="https://example.org/schema.rng"' in pi


def test_extract_xml_model_pi_returns_none_when_absent():
    assert extract_xml_model_pi("<?xml version='1.0'?><TEI/>") is None


def test_detect_language_reads_xml_lang():
    root = ET.fromstring(SAMPLE_TEI.split("?>\n", 2)[-1])
    assert detect_language(root) == Language.DE


def test_detect_language_returns_none_for_unknown():
    root = ET.fromstring(
        '<TEI xml:lang="fr" xmlns="http://www.tei-c.org/ns/1.0"/>'
    )
    assert detect_language(root) is None


def test_extract_paragraphs_reads_ids_and_text():
    root = ET.fromstring(SAMPLE_TEI.split("?>\n", 2)[-1])
    paragraphs = extract_paragraphs(root)
    assert [p.id for p in paragraphs] == ["p1", "p2"]
    assert paragraphs[0].text == "Erste Sätze hier."


def test_replace_paragraphs_swaps_children_keeps_id():
    root = ET.fromstring(SAMPLE_TEI.split("?>\n", 2)[-1])
    annotated = {
        "p1": (
            '<p xml:id="p1">'
            '<w lemma="erste" pos="ADJA" xml:id="p1_0010">Erste</w>'
            '</p>'
        ),
    }
    assert replace_paragraphs(root, annotated) == 1
    tei = "http://www.tei-c.org/ns/1.0"
    xmlns = "http://www.w3.org/XML/1998/namespace"
    p1 = next(
        p for p in root.iter(f"{{{tei}}}p")
        if p.get(f"{{{xmlns}}}id") == "p1"
    )
    assert p1.find(f"{{{tei}}}w") is not None


def test_insert_standoff_appends_to_root():
    root = ET.fromstring(SAMPLE_TEI.split("?>\n", 2)[-1])
    insert_standoff(
        root,
        '<standOff><listAnnotation>'
        '<annotation target="#p1_0010" ana="#cat-plant"/>'
        '</listAnnotation></standOff>',
    )
    tei = "http://www.tei-c.org/ns/1.0"
    assert root.find(f"{{{tei}}}standOff") is not None


def test_write_tei_preserves_xml_model_pi(tmp_path: Path):
    root = ET.fromstring(SAMPLE_TEI.split("?>\n", 2)[-1])
    tree = ET.ElementTree(root)
    out = tmp_path / "out.xml"
    pi = '<?xml-model href="https://example.org/schema.rng" type="application/xml"?>'
    write_tei(tree, out, pi)
    text = out.read_text(encoding="utf-8")
    assert text.startswith('<?xml version="1.0" encoding="utf-8"?>')
    assert pi in text
