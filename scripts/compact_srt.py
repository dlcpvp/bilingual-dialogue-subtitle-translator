#!/usr/bin/env python3
"""Prepare compact translation tasks and assemble SRT without regenerating timing.

Translation rows: index<TAB>Chinese[<TAB>corrected English]. Standard library only.
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


def prepare(source, max_chars=16000):
    if max_chars < 1:
        raise ValueError("--max-chars must be positive")
    source = Path(source).resolve()
    source_hash = digest(source)
    blocks = read_srt(source)
    rows = [f"{index}\t{' '.join(body.split())}" for index, _, body in blocks]
    ranges = []
    start, size = 0, 0
    for position, row in enumerate(rows):
        if position > start and size + len(row) + 1 > max_chars:
            ranges.append([start, position])
            start, size = position, 0
        size += len(row) + 1
    ranges.append([start, len(rows)])

    workdir = prepare_workdir(tempfile.mkdtemp(prefix="bilingual-srt-"))
    manifest = {"source": str(source), "sha256": source_hash, "ranges": ranges}
    (workdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for part, (start, end) in enumerate(ranges, 1):
        lines = [f"Translate only IDs {blocks[start][0]}-{blocks[end - 1][0]}."]
        if start:
            lines += ["CONTEXT BEFORE (do not output):", *rows[max(0, start - 2):start]]
        lines += ["TARGET (ID<TAB>English):", *rows[start:end]]
        if end < len(rows):
            lines += ["CONTEXT AFTER (do not output):", *rows[end:end + 2]]
        (workdir / f"task_{part}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[PASS] {len(blocks)} cues; {len(ranges)} translation task(s)")
    print(f"Workdir: {workdir}")
    print("Read task_<N>.txt; write translation_<N>.tsv in this workdir.")
    return workdir


def read_translation(path, expected_blocks):
    lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    if len(lines) != len(expected_blocks):
        raise ValueError(f"{path.name}: expected {len(expected_blocks)} rows, found {len(lines)}")
    result = []
    corrections = 0
    for line, (index, timestamp, body) in zip(lines, expected_blocks):
        fields = line.split("\t")
        if len(fields) not in (2, 3) or fields[0] != index:
            raise ValueError(f"{path.name}: expected ID {index} and 2 or 3 tab-separated fields")
        if any(not field.strip() for field in fields):
            raise ValueError(f"{path.name}: empty field at ID {index}")
        english = " ".join(body.split())
        if len(fields) == 3:
            corrected = fields[2].strip()
            corrections += corrected != english
            english = corrected
        result.append((index, timestamp, f"{english}\n{fields[1].strip()}"))
    return result, corrections


def finish(workdir, output=None, overwrite=False, keep_workdir=False):
    workdir = Path(workdir).resolve()
    manifest = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
    source = Path(manifest["source"]).resolve()
    output = Path(output).resolve() if output else source.with_name(source.stem + "_bilingual.srt")
    if output == source or (output.exists() and output.samefile(source)):
        raise ValueError("Output must not overwrite the source")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output}; choose another name or authorize --overwrite")
    if not workdir.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError("Workdir must be inside the system temporary directory")
    validate_cleanup_target(workdir, source, output)
    if digest(source) != manifest["sha256"]:
        raise ValueError("Source changed after preparation; prepare a new translation task")
    blocks = read_srt(source)
    translated, corrections, next_start = [], 0, 0
    for part, (start, end) in enumerate(manifest["ranges"], 1):
        if start != next_start or not start < end <= len(blocks):
            raise ValueError("Invalid or nonconsecutive task ranges")
        chunk, changed = read_translation(workdir / f"translation_{part}.tsv", blocks[start:end])
        translated.extend(chunk)
        corrections += changed
        next_start = end
    formatted = validate_against_source(blocks, translated)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w" if overwrite else "x", encoding="utf-8", newline="\n") as handle:
        handle.write("\n\n".join(formatted) + "\n")
    first = blocks[0][1].split(" --> ")[0]
    last = blocks[-1][1].split(" --> ")[1]
    print(f"[PASS] {len(blocks)} bilingual cues; {first} --> {last}; {corrections} English corrections")
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
    prep.add_argument("--max-chars", type=int, default=16000, help="Target English characters per task (not tokens)")
    render = modes.add_parser("finish", help="Validate translations, assemble SRT, clean temporary files")
    render.add_argument("--workdir", required=True)
    render.add_argument("--output")
    render.add_argument("--overwrite", action="store_true")
    render.add_argument("--keep-workdir", action="store_true")
    args = parser.parse_args()
    try:
        if args.mode == "prepare":
            prepare(args.source, args.max_chars)
        else:
            finish(args.workdir, args.output, args.overwrite, args.keep_workdir)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    main()
