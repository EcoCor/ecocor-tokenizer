"""TEI file I/O helpers — no spaCy dependency, safe to unit-test alone."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as _xml_escape

from .tokenizer import Language, Paragraph

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"

ET.register_namespace("", TEI_NS)

PROLOG_PI_RE = re.compile(r"<\?xml-model[^?]*\?>", re.DOTALL)


# ---- taxonomy constants ------------------------------------------------

STTS_TAXONOMY = """\
    <taxonomy xml:id="stts">
      <desc>Stuttgart-Tübingen Tagset (STTS) for German POS tagging.
      Reference: https://www.ims.uni-stuttgart.de/documents/ressourcen/lexika/tagsets/stts-1999.pdf</desc>
      <category xml:id="stts-ADJA"><catDesc>Attributive adjective</catDesc></category>
      <category xml:id="stts-ADJD"><catDesc>Predicative/adverbial adjective</catDesc></category>
      <category xml:id="stts-ADV"><catDesc>Adverb</catDesc></category>
      <category xml:id="stts-APPR"><catDesc>Preposition</catDesc></category>
      <category xml:id="stts-APPRART"><catDesc>Preposition with fused article</catDesc></category>
      <category xml:id="stts-APPO"><catDesc>Postposition</catDesc></category>
      <category xml:id="stts-APZR"><catDesc>Right part of circumposition</catDesc></category>
      <category xml:id="stts-ART"><catDesc>Article</catDesc></category>
      <category xml:id="stts-CARD"><catDesc>Cardinal number</catDesc></category>
      <category xml:id="stts-FM"><catDesc>Foreign material</catDesc></category>
      <category xml:id="stts-ITJ"><catDesc>Interjection</catDesc></category>
      <category xml:id="stts-KOKOM"><catDesc>Comparative conjunction</catDesc></category>
      <category xml:id="stts-KON"><catDesc>Coordinating conjunction</catDesc></category>
      <category xml:id="stts-KOUI"><catDesc>Subordinating conjunction with zu + infinitive</catDesc></category>
      <category xml:id="stts-KOUS"><catDesc>Subordinating conjunction</catDesc></category>
      <category xml:id="stts-NE"><catDesc>Proper noun</catDesc></category>
      <category xml:id="stts-NN"><catDesc>Common noun</catDesc></category>
      <category xml:id="stts-NNE"><catDesc>Proper noun (variant)</catDesc></category>
      <category xml:id="stts-PDAT"><catDesc>Demonstrative pronoun (attributive)</catDesc></category>
      <category xml:id="stts-PDS"><catDesc>Demonstrative pronoun (substituting)</catDesc></category>
      <category xml:id="stts-PIAT"><catDesc>Indefinite pronoun (attributive)</catDesc></category>
      <category xml:id="stts-PIS"><catDesc>Indefinite pronoun (substituting)</catDesc></category>
      <category xml:id="stts-PPER"><catDesc>Personal pronoun</catDesc></category>
      <category xml:id="stts-PPOSAT"><catDesc>Possessive pronoun (attributive)</catDesc></category>
      <category xml:id="stts-PPOSS"><catDesc>Possessive pronoun (substituting)</catDesc></category>
      <category xml:id="stts-PRELAT"><catDesc>Relative pronoun (attributive)</catDesc></category>
      <category xml:id="stts-PRELS"><catDesc>Relative pronoun (substituting)</catDesc></category>
      <category xml:id="stts-PRF"><catDesc>Reflexive pronoun</catDesc></category>
      <category xml:id="stts-PROAV"><catDesc>Pronominal adverb</catDesc></category>
      <category xml:id="stts-PTKA"><catDesc>Particle with adjective/adverb</catDesc></category>
      <category xml:id="stts-PTKANT"><catDesc>Answer particle</catDesc></category>
      <category xml:id="stts-PTKNEG"><catDesc>Negation particle</catDesc></category>
      <category xml:id="stts-PTKVZ"><catDesc>Separable verb prefix</catDesc></category>
      <category xml:id="stts-PTKZU"><catDesc>zu particle</catDesc></category>
      <category xml:id="stts-PWAT"><catDesc>Interrogative pronoun (attributive)</catDesc></category>
      <category xml:id="stts-PWAV"><catDesc>Interrogative/relative adverb</catDesc></category>
      <category xml:id="stts-TRUNC"><catDesc>Truncated word</catDesc></category>
      <category xml:id="stts-VAFIN"><catDesc>Finite auxiliary verb</catDesc></category>
      <category xml:id="stts-VAIMP"><catDesc>Imperative auxiliary verb</catDesc></category>
      <category xml:id="stts-VAINF"><catDesc>Infinitive auxiliary verb</catDesc></category>
      <category xml:id="stts-VAPP"><catDesc>Past participle auxiliary verb</catDesc></category>
      <category xml:id="stts-VMFIN"><catDesc>Finite modal verb</catDesc></category>
      <category xml:id="stts-VMINF"><catDesc>Infinitive modal verb</catDesc></category>
      <category xml:id="stts-VMPP"><catDesc>Past participle modal verb</catDesc></category>
      <category xml:id="stts-VVFIN"><catDesc>Finite full verb</catDesc></category>
      <category xml:id="stts-VVIMP"><catDesc>Imperative full verb</catDesc></category>
      <category xml:id="stts-VVINF"><catDesc>Infinitive full verb</catDesc></category>
      <category xml:id="stts-VVIZU"><catDesc>Infinitive full verb with zu</catDesc></category>
      <category xml:id="stts-VVPP"><catDesc>Past participle full verb</catDesc></category>
      <category xml:id="stts-XY"><catDesc>Non-word</catDesc></category>
    </taxonomy>"""

ENTITY_TAXONOMY = """\
    <taxonomy xml:id="ecocor-entity-types">
      <category xml:id="cat-animal"><catDesc>Animal — Animalia</catDesc></category>
      <category xml:id="cat-plant"><catDesc>Plant — Plantae</catDesc></category>
    </taxonomy>"""

ENTITY_TAXONOMY_WITH_HABITAT = """\
    <taxonomy xml:id="ecocor-entity-types">
      <category xml:id="cat-animal"><catDesc>Animal — Animalia</catDesc></category>
      <category xml:id="cat-plant"><catDesc>Plant — Plantae</catDesc></category>
      <category xml:id="cat-habitat"><catDesc>Habitat — landscape, water body, terrain</catDesc></category>
    </taxonomy>"""


# ---- source metadata extraction ----------------------------------------


def extract_source_meta(root: ET.Element) -> dict:
    """Extract xml:id, title, and author from a TEI root element."""
    source_id = root.get(f"{{{XML_NS}}}id", "")
    title_el = root.find(f".//{{{TEI_NS}}}titleStmt/{{{TEI_NS}}}title")
    author_el = root.find(f".//{{{TEI_NS}}}titleStmt/{{{TEI_NS}}}author")
    return {
        "id": source_id,
        "title": (title_el.text or "").strip() if title_el is not None else "",
        "author": (author_el.text or "").strip() if author_el is not None else "",
    }


# ---- layer TEI writer ---------------------------------------------------


def write_layer_tei(
    path: Path,
    list_annotation_xml: str,
    *,
    source_id: str,
    layer_type: str,
    title: str,
    source_filename: str,
    resp_name: str,
    resp_type: str = "automated annotation",
    taxonomy_xml: str = "",
    app_ident: str = "",
    app_version: str = "",
    app_desc: str = "",
    app_url: str = "",
    gen_date: Optional[str] = None,
) -> None:
    """Write an annotation layer as a full TEI document with teiHeader.

    Parameters:
      list_annotation_xml:  the <listAnnotation> fragment (no <standOff> wrapper)
      source_id:            xml:id of the source TEI (e.g. "eco_de_000033")
      layer_type:           layer name (e.g. "linguistic", "entity", "ntee", "gold")
      title:                human-readable title for the layer document
      source_filename:      filename of the vanilla TEI this layer annotates
      resp_name:            who/what produced the layer
      resp_type:            "automated annotation" | "manual annotation" | etc.
      taxonomy_xml:         taxonomy declaration block (use constants above)
      app_ident:            application identifier (for <appInfo>), omit for manual
      app_version:          application version
      app_desc:             application label (tool name, model, etc.)
      app_url:              application URL (emitted as <ref> inside <application>)
      gen_date:             generation date (default: today)
    """
    if gen_date is None:
        gen_date = date.today().isoformat()

    layer_id = f"{source_id}_{layer_type}" if source_id else layer_type

    # Build optional sections
    class_decl = ""
    if taxonomy_xml:
        class_decl = f"  <classDecl>\n{taxonomy_xml}\n  </classDecl>"

    app_info = ""
    if app_ident:
        ref_line = ""
        if app_url:
            ref_line = f'\n      <ref target="{_esc(app_url)}"/>'
        app_info = (
            f"  <appInfo>\n"
            f"    <application ident=\"{_esc(app_ident)}\" version=\"{_esc(app_version)}\">\n"
            f"      <label>{_esc(app_desc or app_ident)}</label>{ref_line}\n"
            f"    </application>\n"
            f"  </appInfo>"
        )

    encoding_desc = ""
    if class_decl or app_info:
        parts = [p for p in [class_decl, app_info] if p]
        encoding_desc = "<encodingDesc>\n" + "\n".join(parts) + "\n</encodingDesc>"

    body = f"""\
<?xml version="1.0" encoding="utf-8"?>
<TEI xml:id="{_esc(layer_id)}" type="annotation" xmlns="{TEI_NS}">
<teiHeader>
  <fileDesc>
    <titleStmt>
      <title>{_esc(title)}</title>
      <respStmt>
        <resp>{_esc(resp_type)}</resp>
        <name>{_esc(resp_name)}</name>
      </respStmt>
    </titleStmt>
    <publicationStmt>
      <publisher>EcoCor</publisher>
      <availability>
        <licence target="https://creativecommons.org/licenses/by/4.0/"/>
      </availability>
    </publicationStmt>
    <sourceDesc>
      <bibl>
        <ref type="source" target="{_esc(source_filename)}">{_esc(source_filename)}</ref>
      </bibl>
    </sourceDesc>
  </fileDesc>
  {encoding_desc}
  <revisionDesc>
    <change when="{_esc(gen_date)}">Generated</change>
  </revisionDesc>
</teiHeader>
<standOff>
  {list_annotation_xml}
</standOff>
</TEI>
"""

    path.write_text(body, encoding="utf-8")


def _esc(s: str) -> str:
    return _xml_escape(s, {'"': "&quot;", "'": "&apos;"})


def mark_as_tokenized(root: ET.Element) -> str:
    """Set type="tokenized" on the TEI root and append _tokenized to xml:id.

    Returns the new xml:id (used by layer files to reference the source).
    """
    source_id = root.get(f"{{{XML_NS}}}id", "")
    new_id = f"{source_id}_tokenized" if source_id else "tokenized"
    root.set(f"{{{XML_NS}}}id", new_id)
    root.set("type", "tokenized")
    return new_id


def prepare_tokenized_header(root: ET.Element) -> None:
    """Clean up the teiHeader for the tokenized output.

    - Remove ELTeC schema reference (handled separately via xml-model PI)
    - Set encodingDesc/@n to "ecocor-tokenized"
    - Add EcoCor respStmt to titleStmt
    - Remove <extent>
    """
    header = root.find(f"{{{TEI_NS}}}teiHeader")
    if header is None:
        return

    file_desc = header.find(f"{{{TEI_NS}}}fileDesc")
    if file_desc is not None:
        # Remove <extent>
        for extent in file_desc.findall(f"{{{TEI_NS}}}extent"):
            file_desc.remove(extent)

        # Add EcoCor respStmt to titleStmt
        title_stmt = file_desc.find(f"{{{TEI_NS}}}titleStmt")
        if title_stmt is not None:
            resp_stmt = ET.SubElement(title_stmt, f"{{{TEI_NS}}}respStmt")
            resp = ET.SubElement(resp_stmt, f"{{{TEI_NS}}}resp")
            resp.text = "EcoCor conversion"
            name = ET.SubElement(resp_stmt, f"{{{TEI_NS}}}name")
            name.text = "ecocor-tokenizer"

    # Update encodingDesc
    enc_desc = header.find(f"{{{TEI_NS}}}encodingDesc")
    if enc_desc is not None:
        enc_desc.set("n", "ecocor-tokenized")
        # Clear old content (e.g. empty <p/> from ELTeC)
        for child in list(enc_desc):
            enc_desc.remove(child)
        enc_desc.text = None
        p = ET.SubElement(enc_desc, f"{{{TEI_NS}}}p")
        p.text = "Tokenized TEI with vanilla <w> and <pc> elements."
    else:
        # Create encodingDesc if missing
        enc_desc = ET.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
        enc_desc.set("n", "ecocor-tokenized")
        p = ET.SubElement(enc_desc, f"{{{TEI_NS}}}p")
        p.text = "Tokenized TEI with vanilla <w> and <pc> elements."


# ---- existing helpers (unchanged) ----------------------------------------


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
