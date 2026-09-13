# Conservative Dialogue ASR Correction Guide

The English subtitles may come from speech recognition and contain missing punctuation, homophones, malformed names, or words that conflict with the local topic. Without audio, correct them conservatively.

## Evidence required

Replace a word or phrase only when several signals agree:

- the source phrase is implausible in its sentence;
- the proposed wording is phonetically plausible;
- nearby cues, repeated terminology, formulas, or named entities support it;
- the replacement does not invent or "fact-check away" the speaker's claim.

Punctuation and obvious casing fixes require less evidence than word replacement. Context from neighboring cues is especially important because one thought may span several timestamps.

Use exceptional caution with negation, numbers, grades, dates, units, personal names, citations, formulas, and assessment instructions. When the evidence is insufficient, keep the source wording and translate the uncertainty conservatively.

## Historical examples, not replacement rules

The following pairs illustrate contextual reasoning from particular recordings. Never search-and-replace them globally or reuse a correction merely because it appears here:

| Raw ASR text | Possible intended English | Context that could support it |
| --- | --- | --- |
| `play your eyes` | `plagiarize` | discussion of citation or academic integrity |
| `a few waves` | `a few A's` | discussion of grades or grading curves |
| `Coach E` | `GE` / `General Electric` | discussion of Jeffrey Immelt or the company |
| `plane classes` | `plane crashes` | discussion of aviation accidents |
| `freedom in the streets` | `Freedom Industries` | discussion of the 2014 West Virginia chemical spill |
| `Couple Joe` | `cup of joe` | discussion of coffee |

These examples are candidates only. The actual transcript context remains the deciding evidence.

## Spoken-language handling

- Preserve meaningful discourse markers, questions, self-corrections, emphasis, and substantive repetition.
- A filler sound with no semantic role may be omitted, but do not polish the speaker into a different argument.
- Do not move words between SRT cues even when a sentence crosses a timestamp boundary.
- Do not silently turn an awkward or mistaken statement into a textbook-correct claim.
- Keep the corrected English and Chinese meaning aligned within each cue.
