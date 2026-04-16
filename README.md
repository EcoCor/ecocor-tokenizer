# ecocor-tokenizer

Command-line tool that turns an EcoCor TEI file into the new
token-level format: every `<p xml:id="…">` in `<body>` gets tokenized
into `<w>` / `<pc>` children with stable xml:ids, `@lemma`, and `@pos`
(STTS for German), and plant / animal mentions are emitted as a
`<standOff>` block of minimal `<annotation>` elements.

Conventions come from
[../notes/standoff-annotation-proposal.md](../notes/standoff-annotation-proposal.md).
Reference output:
[../examples/1807_Kleist_Erdbeben.tokenized-sample.xml](../examples/1807_Kleist_Erdbeben.tokenized-sample.xml).

## Install

Requires Python ≥ 3.10. One `make install` sets up a venv, pulls the
runtime deps, and — critically — installs the spaCy German/English
models from pinned release wheels (no separate `python -m spacy
download` step needed).

```sh
make install
source .venv/bin/activate
```

Behind the scenes that runs:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # spacy + pinned model wheels
.venv/bin/pip install -e .                  # installs the CLI entry point
```

The spaCy model wheels are pinned in
[requirements.txt](requirements.txt):

- `de_core_news_sm` 3.8.0 — POS tags are STTS
- `en_core_web_sm` 3.8.0 — POS tags are Penn Treebank

First `pip install` downloads ~50 MB per model. They land inside the
venv; `make clean` nukes them alongside the rest.

## Use

```sh
# inline — tokenized TEI with <standOff> appended (single file)
ecocor-tokenize IN.xml -o OUT.xml

# split — stand-off written to a separate file (matches the
# annotations/{layer}/{corpus}/{text}.xml layout in the proposal)
ecocor-tokenize IN.xml -o OUT.xml --annotations-out OUT.standoff.xml

# overrides
ecocor-tokenize IN.xml -o OUT.xml --language de --entity-list URL
```

Language is detected from `TEI/@xml:lang`. The entity word list
defaults to the language's built-in list (currently from
`ecocor-extractor/word_list`); pass `--entity-list URL` to override.

Also runnable without installation via `python -m ecocor_tokenizer …`.

## Test

```sh
make test
```

Runs the pure-logic tests ([tests/test_pure.py](tests/test_pure.py),
[tests/test_tei_io.py](tests/test_tei_io.py)) — no spaCy models needed
for those. End-to-end tests that load a model are worth adding once
the pipeline is stable.

## Layout

```
ecocor_tokenizer/
  tokenizer.py   core pipeline: pydantic models, id scheme, TEI
                 fragment emission, entity matching, spaCy glue
  tei.py         TEI file I/O: parse, replace paragraphs, insert
                 <standOff>, write (preserves <?xml-model?> PI)
  cli.py         argparse front-end, wires the two together
  __main__.py    entry point for python -m ecocor_tokenizer
```

Pure logic is kept free of spaCy so helpers can be unit-tested without
loading models.
