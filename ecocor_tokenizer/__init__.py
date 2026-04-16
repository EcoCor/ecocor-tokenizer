"""EcoCor TEI tokenizer.

Turns EcoCor TEI documents into the new token-level format:

- every `<p xml:id="...">` in `<body>` is tokenized into `<w>`/`<pc>`
  children carrying stable xml:ids, @lemma, and @pos (STTS for German);
- plant / animal mentions are emitted as a `<standOff>` block with
  minimal `<annotation target="#..." ana="#cat-..." corresp="..."/>`
  elements pointing at the token ids.

See ../notes/standoff-annotation-proposal.md for the conventions.
"""

from .tokenizer import (
    AnnotateRequest,
    AnnotateResponse,
    Language,
    Paragraph,
    annotate,
)

__all__ = [
    "AnnotateRequest",
    "AnnotateResponse",
    "Language",
    "Paragraph",
    "annotate",
]
