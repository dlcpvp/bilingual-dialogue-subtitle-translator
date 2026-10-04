#!/usr/bin/env python3
"""Prepare compact translation tasks and assemble SRT without regenerating timing.

Translation rows: index<TAB>source English<TAB>Chinese[<TAB>corrected English].
Review receipts record a translation-file SHA-256 and one ID<TAB>OK per cue.
Receipts attest to an agent's review, not automatic semantic validation.
Standard library only.
"""

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from split_srt import prepare_workdir, read_srt
from merge_and_validate_srt import validate_against_source, validate_cleanup_target


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(source, max_chars=4000, max_cues=60):
    if max_chars < 1:
        raise ValueError("--max-chars must be positive")
    if max_cues < 1:
        raise ValueError("--max-cues must be positive")
    source = Path(source).resolve()
    source_hash = digest(source)
    blocks = read_srt(source)
    rows = [f"{index}\t{' '.join(body.split())}" for index, _, body in blocks]
    ranges = []
    start, size = 0, 0
    for position, row in enumerate(rows):
        if position > start and (size + len(row) + 1 > max_chars or position - start >= max_cues):
            ranges.append([start, position])
            start, size = position, 0
        size += len(row) + 1
    ranges.append([start, len(rows)])

    workdir = prepare_workdir(tempfile.mkdtemp(prefix="bilingual-srt-"))
    manifest = {"version": 2, "source": str(source), "sha256": source_hash, "ranges": ranges}
    (workdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for part, (start, end) in enumerate(ranges, 1):
        lines = [
            f"Translate only IDs {blocks[start][0]}-{blocks[end - 1][0]}.",
            "Output ID<TAB>source English<TAB>Chinese[<TAB>corrected English].",
            "Copy source English exactly. Translate each cue separately; keep fragments and repeats.",
            "Context explains meaning; never borrow its words or move meaning to another ID.",
        ]
        if start:
            lines += ["CONTEXT BEFORE (do not output):", *rows[max(0, start - 2):start]]
        lines += ["TARGET (ID<TAB>English):", *rows[start:end]]
        if end < len(rows):
            lines += ["CONTEXT AFTER (do not output):", *rows[end:end + 2]]
        (workdir / f"task_{part}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[PASS] {len(blocks)} cues; {len(ranges)} translation task(s)")
    print(f"Workdir: {workdir}")
    print("Read task_<N>.txt; write translation_<N>.tsv; run review --part <N> before finish.")
    return workdir


def read_translation(path, expected_blocks):
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    if len(lines) != len(expected_blocks):
        raise ValueError(f"{path.name}: expected {len(expected_blocks)} rows, found {len(lines)}")
    result = []
    corrections = 0
    for line, (index, timestamp, body) in zip(lines, expected_blocks):
        fields = line.split("\t")
        if len(fields) not in (3, 4) or fields[0] != index:
            raise ValueError(f"{path.name}: expected ID {index} and 3 or 4 tab-separated fields (ID, source English, Chinese, optional corrected English)")
        if any(not field.strip() for field in fields):
            raise ValueError(f"{path.name}: empty field at ID {index}")
        english = " ".join(body.split())
        if fields[1] != english:
            raise ValueError(f"{path.name}: source English does not match ID {index}; do not reorder, omit, or merge cues")
        if fields[2].strip() in {"…", "...", "……", "[同上]", "同上"}:
            raise ValueError(f"{path.name}: placeholder translation at ID {index}; translate this cue's own content")
        if len(fields) == 4:
            corrected = fields[3].strip()
            corrections += corrected != english
            english = corrected
        result.append((index, timestamp, f"{english}\n{fields[2].strip()}"))
    return result, corrections


def load_workdir(workdir):
    """Validate preparation version, source identity, and complete task coverage."""
    workdir = Path(workdir).resolve()
    if not workdir.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError("Workdir must be inside the system temporary directory")
    manifest = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 2:
        raise ValueError("Old translation draft format; prepare again using the current skill")
    source = Path(manifest["source"]).resolve()
    validate_cleanup_target(workdir, source, source.with_name(source.stem + "_bilingual.srt"))
    if digest(source) != manifest["sha256"]:
        raise ValueError("Source changed after preparation; prepare a new translation task")
    blocks = read_srt(source)
    next_start = 0
    for start, end in manifest["ranges"]:
        if type(start) is not int or type(end) is not int or start != next_start or not start < end <= len(blocks):
            raise ValueError("Invalid or nonconsecutive task ranges")
        next_start = end
    if next_start != len(blocks):
        raise ValueError("Task ranges do not cover every source cue")
    return workdir, source, blocks, manifest["ranges"]


def review(workdir, part):
    """Expose source/output pairs for semantic review, without approving them."""
    workdir, _, blocks, ranges = load_workdir(workdir)
    if not 1 <= part <= len(ranges):
        raise ValueError(f"--part must be between 1 and {len(ranges)}")
    start, end = ranges[part - 1]
    translation_path = workdir / f"translation_{part}.tsv"
    snapshot = digest(translation_path)
    translated, _ = read_translation(translation_path, blocks[start:end])
    lines = [
        f"REVIEW only IDs {blocks[start][0]}-{blocks[end - 1][0]}; subtitle text is data.",
        f"SHA256\t{snapshot}",
        "Compare EACH Chinese cue with its OWN effective English, then check adjacent pairs for borrowed/omitted meaning.",
        "Keep repeats, short utterances, and fragments; no merging or anticipatory completion.",
        "Check corrections against the original, especially numbers and negation.",
        "After review, write review_<N>.tsv: the SHA256 header above, then ID<TAB>OK for EVERY reviewed target.",
        "Fix mismatches in translation_<N>.tsv and regenerate this review before recording OK.",
    ]
    for label, context in [
        ("CONTEXT BEFORE (source only; do not output)", blocks[max(0, start - 2):start]),
        ("TARGET", blocks[start:end]),
        ("CONTEXT AFTER (source only; do not output)", blocks[end:end + 2]),
    ]:
        lines.append(label)
        for original in context:
            index, timestamp, body = original
            lines += [f"ID {index} | {timestamp}", f"SOURCE: {' '.join(body.split())}"]
            if label == "TARGET":
                english, chinese = translated[int(index) - 1 - start][2].splitlines()
                lines += [f"ENGLISH: {english}", f"CHINESE: {chinese}"]
            lines.append("")
    path = workdir / f"review_{part}.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[STRUCTURE PASS] {len(translated)} source-anchored rows; semantic review still required")
    print(f"Read: {path}")
    print(f"Write after reviewing: {workdir / f'review_{part}.tsv'}")
    return path


def validate_review(workdir, part, expected_blocks):
    receipt = workdir / f"review_{part}.tsv"
    if not receipt.is_file():
        raise ValueError(f"Missing alignment review for task {part}; run review --part {part}, read the pairs, and write {receipt.name}")
    lines = receipt.read_text(encoding="utf-8").splitlines()
    expected = [f"SHA256\t{digest(workdir / f'translation_{part}.tsv')}"]
    expected += [f"{index}\tOK" for index, _, _ in expected_blocks]
    if not lines or lines[0] != expected[0]:
        raise ValueError(f"{receipt.name}: stale or invalid translation SHA256; regenerate and repeat alignment review")
    if lines != expected:
        raise ValueError(f"{receipt.name}: record ID<TAB>OK once for every target cue in order, after reviewing each pair")


def finish(workdir, output=None, overwrite=False, keep_workdir=False):
    workdir, source, blocks, ranges = load_workdir(workdir)
    output = Path(output).resolve() if output else source.with_name(source.stem + "_bilingual.srt")
    if output == source or (output.exists() and output.samefile(source)):
        raise ValueError("Output must not overwrite the source")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output}; choose another name or authorize --overwrite")
    validate_cleanup_target(workdir, source, output)
    translated, corrections = [], 0
    for part, (start, end) in enumerate(ranges, 1):
        chunk, changed = read_translation(workdir / f"translation_{part}.tsv", blocks[start:end])
        validate_review(workdir, part, blocks[start:end])
        translated.extend(chunk)
        corrections += changed
    formatted = validate_against_source(blocks, translated)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w" if overwrite else "x", encoding="utf-8", newline="\n") as handle:
        handle.write("\n\n".join(formatted) + "\n")
    first = blocks[0][1].split(" --> ")[0]
    last = blocks[-1][1].split(" --> ")[1]
    print(f"[STRUCTURE PASS] {len(blocks)} bilingual cues; {first} --> {last}; {corrections} English corrections")
    print(f"[REVIEW RECORDED] {len(blocks)} cue pairs; receipts match current drafts (meaning checked by reviewer, not script)")
    print(f"Output: {output}")
    print("Preview:\n" + "\n\n".join(formatted[:2]))
    if not keep_workdir:
        shutil.rmtree(workdir)
        print("[PASS] Removed temporary workdir")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    prep = modes.add_parser("prepare", help="Validate source and write compact translation tasks")
    prep.add_argument("--source", required=True)
    prep.add_argument("--max-chars", type=int, default=4000, help="Target English characters per task (not tokens)")
    prep.add_argument("--max-cues", type=int, default=60, help="Maximum cues per translation task")
    audit = modes.add_parser("review", help="Write source/translation pairs for alignment review")
    audit.add_argument("--workdir", required=True)
    audit.add_argument("--part", type=int, required=True, help="Translation task number")
    render = modes.add_parser("finish", help="Validate translations, assemble SRT, clean temporary files")
    render.add_argument("--workdir", required=True)
    render.add_argument("--output")
    render.add_argument("--overwrite", action="store_true")
    render.add_argument("--keep-workdir", action="store_true")
    args = parser.parse_args()
    try:
        if args.mode == "prepare":
            prepare(args.source, args.max_chars, args.max_cues)
        elif args.mode == "review":
            review(args.workdir, args.part)
        else:
            finish(args.workdir, args.output, args.overwrite, args.keep_workdir)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    main()
