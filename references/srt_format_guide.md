# SRT Formatting Standards

## Accepted source structure

The source must be a standard English SRT file with consecutive indexes beginning at 1, comma-separated milliseconds, and one or more non-empty text lines:

```srt
1
00:00:00,940 --> 00:00:03,460
I know AI can help generate slides.

2
00:00:05,800 --> 00:00:08,830
I don't want to do your whole thing, but
I'll let you do it.
```

Blank lines separate subtitle blocks. The source may wrap English across several lines inside a block. The workflow does not accept VTT headers, dot-separated VTT timestamps, missing indexes, timestamp settings, or plain timestamped transcripts; convert those formats explicitly before using this skill.

## Required bilingual output

Produce exactly one English line followed by exactly one Simplified Chinese line for every source cue:

```srt
1
00:00:00,940 --> 00:00:03,460
I know AI can help generate slides.
我知道 AI 可以帮助生成幻灯片。

2
00:00:05,800 --> 00:00:08,830
I don't want to do your whole thing, but I'll let you do it.
我不希望它替你完成全部内容，但我允许你们使用它。
```

Within a cue, collapse source line wrapping with single spaces. Never move, merge, or duplicate content across timestamp boundaries. A cue may remain a fragment because cue alignment takes priority over grammatical sentence boundaries.

## Text and file rules

- Preserve the exact source index and timestamp for every cue.
- Use natural English punctuation and full-width Chinese punctuation where appropriate.
- Preserve formulas and symbols as plain text; do not add Markdown math delimiters.
- Keep URLs, citation names, product names, technical terms, and acronyms unless a high-confidence ASR correction is justified.
- Keep both output text lines non-empty. Do not insert headings, speaker labels, notes, Markdown fences, or extra payload lines.
- Encode the result as UTF-8 without BOM with `\n` newlines.
- Name the result `<source_stem>_bilingual.srt` unless the user chooses another name.
