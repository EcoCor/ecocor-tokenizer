# ecocor-tokenizer

Command-line tool that turns EcoCor TEI files into the new token-level
format. Base TEI is vanilla — only `<w>` and `<pc>` with stable
`xml:id`s, no inline linguistic attributes. Linguistic annotations
(POS + lemma) and entity annotations (plant / animal) are emitted as
separate stand-off `<listAnnotation>` layers.

Additional commands extract inline manual annotations and align gold
standard files to existing tokenized texts.

## Install

Requires Python >= 3.10.

```sh
make install
source .venv/bin/activate
```

This creates a venv, installs spaCy + pinned German/English model
wheels (no separate `python -m spacy download` needed), and registers
the CLI entry points.

## Tokenize a TEI file

```sh
# all layers inline in one file (both <listAnnotation> blocks inside
# one <standOff> appended to the TEI)
ecocor-tokenize INPUT.xml -o OUTPUT.xml

# split mode — each layer to its own file
ecocor-tokenize INPUT.xml -o OUTPUT.xml \
    --linguistic-out OUTPUT.linguistic.xml \
    --entity-out OUTPUT.entity.xml

# override language or word list
ecocor-tokenize INPUT.xml -o OUTPUT.xml --language de --entity-list URL
```

Language is auto-detected from `TEI/@xml:lang`.

### Batch-tokenize a full corpus

```sh
mkdir -p eco-de/tokenized
for f in eco-de/tei/*.xml; do
  name=$(basename "$f")
  ecocor-tokenize "$f" \
    -o "eco-de/tokenized/${name}" \
    --linguistic-out "eco-de/tokenized/${name%.xml}.linguistic.xml" \
    --entity-out "eco-de/tokenized/${name%.xml}.entity.xml"
done
```

### Output

Base TEI (`OUTPUT.xml`):

```xml
<w xml:id="eco_de_000033_30_0060">Hauptstadt</w>
```

Linguistic layer (`OUTPUT.linguistic.xml`):

```xml
<listAnnotation type="linguistic">
  <annotation target="#eco_de_000033_30_0060" ana="#stts-NN">
    <note type="lemma">Hauptstadt</note>
  </annotation>
</listAnnotation>
```

Entity layer (`OUTPUT.entity.xml`):

```xml
<listAnnotation type="entity">
  <annotation target="#eco_de_000033_150_1850"
              ana="#cat-animal"
              corresp="https://www.wikidata.org/wiki/Q25334"/>
</listAnnotation>
```

## Extract manual inline annotations

If a colleague annotates the vanilla TEI by wrapping token text in
category elements:

```xml
<w xml:id="eco_de_000033_90_1560"><Tier>Tiere</Tier></w>
<w xml:id="eco_de_000033_110_2730"><Pflanze>Eichen</Pflanze></w>
<w xml:id="eco_de_000033_110_3190"><Lebensraum>Feld</Lebensraum></w>
```

Extract them as a stand-off layer (input file is not modified):

```sh
ecocor-extract-annotations ANNOTATED.xml -o ANNOTATIONS.xml
```

Produces a `<listAnnotation type="ntee">` with category mappings:

- `<Tier>` → `#cat-animal`
- `<Pflanze>` → `#cat-plant`
- `<Lebensraum>` → `#cat-habitat`

## Extract and align gold standard annotations

Gold standard files have a different structure: flat running text in
`<body>` with no `<p>`, no `<w>`, no `xml:id` — just inline
`<Tier>`, `<Pflanze>`, `<Lebensraum>` wrappers in prose. Two modes
handle this.

### Mode 1: self-tokenize (standalone gold texts)

For gold texts that are NOT in the EcoCor corpus. Tokenizes the gold
text with spaCy, assigns token IDs, aligns annotations by character
offset:

```sh
ecocor-extract-gold GOLD.xml \
    -o TOKENIZED.xml \
    --gold-out LAYER.xml \
    --language de
```

Produces both a vanilla TEI and a gold annotation layer. Optionally
also emits a linguistic layer with `--linguistic-out`.

### Mode 2: align to existing vanilla (corpus texts)

For gold texts that correspond to an already-tokenized corpus text.
Matches the gold text to existing `<w>` tokens and emits a gold layer
pointing at the existing token IDs — no new tokenization:

```sh
ecocor-extract-gold GOLD.xml \
    --align-to VANILLA.xml \
    --gold-out LAYER.xml \
    --language de
```

### How alignment works

The gold text includes material not present in the vanilla `<w>`
tokens — chapter headings, stage directions, character names — because
those live in `<head>` / `<front>` elements that the tokenizer skips.

A naive greedy match (match each word forward) fails badly (~8%) because
common heading words like "Blatt" accidentally match body text at wrong
positions, causing the alignment pointer to jump ahead and lose sync.

The alignment uses a **two-phase strategy**:

1. **Seek phase**: scans for a candidate match with a 500-token
   lookahead, but requires **3 consecutive matching tokens** to confirm.
   This prevents heading words from causing false jumps.

2. **Run phase**: once confirmed, does fast 1:1 greedy matching with a
   10-token lookahead for minor tokenization differences. When sync is
   lost (e.g. at the next chapter heading), drops back to seek phase.

Tested on Raabe *Pfisters Mühle* (gold = first third of the novel,
~17K words; vanilla = full novel, ~52K tokens):

- **99% word alignment** (16,994 / 17,140 gold words matched)
- **98% annotation mapping** (240 / 245 annotations)
- The 5 unmapped annotations were in chapter headings with no
  corresponding `<w>` tokens — expected and acceptable.

### Known limitations

- **Alignment depends on identical surface forms.** If the gold text
  has different orthography or normalization than the corpus TEI
  (e.g. "müße" vs. "müsse"), tokens won't match. No fuzzy matching
  is implemented yet.
- **Headings produce gaps.** Annotations on heading words (chapter
  titles, character names in drama) cannot be mapped because our
  tokenizer only processes `<p xml:id>` content, not `<head>`.
- **Long structural gaps** (>500 words of non-paragraph material)
  can exceed the seek lookahead. Unlikely in prose, possible in
  drama with long cast lists.
- **Gold files wrap single words only.** No multi-token annotations
  exist in the current gold data, so multi-token alignment is
  untested.

### Recommendation for new gold annotations

Annotate directly on the vanilla tokenized TEI (like the ntee
workflow) rather than on flat text. This eliminates the alignment
step entirely — `ecocor-extract-annotations` reads the token IDs
directly, no character-offset matching needed.

## Test

```sh
make test
```

Pure-logic tests (no spaCy models needed). 18 tests covering token id
scheme, vanilla TEI emission, linguistic + entity layer rendering,
TEI file I/O.

## Layout

```
ecocor_tokenizer/
  tokenizer.py   core: pydantic models, id scheme, vanilla TEI emission,
                 linguistic + entity layer rendering, spaCy glue
  tei.py         TEI file I/O: parse, replace paragraphs, insert
                 <standOff>, write (preserves <?xml-model?> PI)
  cli.py         argparse front-end for ecocor-tokenize
  extract.py     ecocor-extract-annotations (ntee inline → stand-off)
  gold.py        ecocor-extract-gold (gold standard → stand-off, with
                 self-tokenize or align-to-vanilla modes)
  __main__.py    entry point for python -m ecocor_tokenizer
```
