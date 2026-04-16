# ecocor-tokenizer

Command-line tool that turns EcoCor TEI files into the new token-level
format. Base TEI is vanilla — only `<w>` and `<pc>` with stable
`xml:id`s, no inline linguistic attributes. Linguistic annotations
(POS + lemma) and entity annotations (plant / animal) are emitted as
separate stand-off `<listAnnotation>` layers.

A second command extracts inline manual annotations (e.g. from a
colleague's `<Tier>`, `<Pflanze>`, `<Lebensraum>` markup) into a
stand-off layer.

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
  extract.py     argparse front-end for ecocor-extract-annotations
  __main__.py    entry point for python -m ecocor_tokenizer
```
