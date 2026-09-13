#!/usr/bin/env python3
"""Merge translated SRT chunks and validate them against the source SRT."""

import argparse
import re
import shutil
from pathlib import Path

from split_srt import (
    WORKDIR_MARKER,
    WORKDIR_MARKER_CONTENT,
    parse_srt,
    read_srt,
)


TRANSLATED_CHUNK_RE = re.compile(r"translated_part(\d+)\.srt", re.IGNORECASE)


def translated_chunk_files(chunks_dir):
    chunks_dir = Path(chunks_dir)
    matches = []
    for path in chunks_dir.glob("translated_part*.srt"):
        match = TRANSLATED_CHUNK_RE.fullmatch(path.name)
        if match:
            matches.append((int(match.group(1)), path))
    matches.sort(key=lambda item: item[0])

    if not matches:
        raise FileNotFoundError(f"No translated_part<N>.srt files found in {chunks_dir}")

    part_numbers = [number for number, _ in matches]
    expected_parts = list(range(1, len(matches) + 1))
    if part_numbers != expected_parts:
        raise ValueError(
            f"Translated chunk numbers must be consecutive from 1; found {part_numbers}"
        )
    return [path for _, path in matches]


def read_translated_chunks(chunks_dir):
    all_blocks = []
    for path in translated_chunk_files(chunks_dir):
        with path.open("r", encoding="utf-8-sig", errors="strict", newline=None) as handle:
            blocks = parse_srt(handle.read(), str(path), expected_start=len(all_blocks) + 1)
        all_blocks.extend(blocks)
        print(f"Read {path.name}: {len(blocks)} blocks")
    return all_blocks


def read_bilingual_srt(path):
    """Read a finished bilingual SRT while enforcing its output encoding contract."""
    path = Path(path)
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"Bilingual output must be UTF-8 without BOM: {path}")
    if b"\r" in raw:
        raise ValueError(f"Bilingual output must use LF newlines: {path}")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Bilingual output is not valid UTF-8: {path}") from exc
    return parse_srt(content, str(path))


def validate_against_source(source_blocks, translated_blocks):
    if len(translated_blocks) != len(source_blocks):
        raise ValueError(
            f"Block count mismatch: source has {len(source_blocks)}, translation has {len(translated_blocks)}"
        )

    formatted_blocks = []
    for source, translated in zip(source_blocks, translated_blocks):
        source_index, source_timestamp, _ = source
        translated_index, translated_timestamp, translated_body = translated

        if translated_index != source_index:
            raise ValueError(f"Index mismatch: expected {source_index}, found {translated_index}")
        if translated_timestamp != source_timestamp:
            raise ValueError(
                f"Timestamp mismatch in block {source_index}: expected {source_timestamp!r}, "
                f"found {translated_timestamp!r}"
            )

        text_lines = [line.strip() for line in translated_body.splitlines() if line.strip()]
        if len(text_lines) != 2:
            raise ValueError(
                f"Block {source_index} must contain exactly two non-empty text lines; "
                f"found {len(text_lines)}"
            )
        english, chinese = text_lines
        formatted_blocks.append(f"{source_index}\n{source_timestamp}\n{english}\n{chinese}")

    return formatted_blocks


def path_is_within(path, directory):
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def validate_cleanup_target(chunks_dir, source_path, output_path):
    """Refuse cleanup unless split_srt.py created this dedicated work directory."""
    chunks_dir = Path(chunks_dir).resolve()
    marker = chunks_dir / WORKDIR_MARKER
    if not marker.is_file():
        raise ValueError(
            f"Refusing automatic cleanup: work-directory marker is missing from {chunks_dir}"
        )
    if marker.read_text(encoding="utf-8") != WORKDIR_MARKER_CONTENT:
        raise ValueError(f"Refusing automatic cleanup: invalid marker in {chunks_dir}")
    if path_is_within(source_path, chunks_dir):
        raise ValueError("Source SRT must not be stored inside the temporary chunks directory")
    if path_is_within(output_path, chunks_dir):
        raise ValueError("Final output must not be stored inside the temporary chunks directory")
    return chunks_dir


def merge_and_validate(source_path, chunks_dir, output_path, overwrite=False, keep_workdir=False):
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()
    if output_path == source_path:
        raise ValueError("Output path must not overwrite the source SRT")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output_path}; use --overwrite to replace it")

    cleanup_target = None
    if not keep_workdir:
        cleanup_target = validate_cleanup_target(
            Path(chunks_dir).resolve(), source_path, output_path
        )

    source_blocks = read_srt(source_path)
    translated_blocks = read_translated_chunks(chunks_dir)
    formatted_blocks = validate_against_source(source_blocks, translated_blocks)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n\n".join(formatted_blocks) + "\n")

    duration = source_blocks[-1][1].split(" --> ", 1)[1]
    print(f"[PASS] Wrote {len(formatted_blocks)} bilingual blocks through {duration}")
    print(f"Output: {output_path}")
    if cleanup_target is not None:
        shutil.rmtree(cleanup_target)
        print(f"[PASS] Removed temporary work directory: {cleanup_target}")


def validate_completed_file(source_path, input_path):
    source_path = Path(source_path).resolve()
    input_path = Path(input_path).resolve()
    if input_path == source_path:
        raise ValueError("Bilingual input must not overwrite the source SRT")

    source_blocks = read_srt(source_path)
    translated_blocks = read_bilingual_srt(input_path)
    validate_against_source(source_blocks, translated_blocks)
    duration = source_blocks[-1][1].split(" --> ", 1)[1]
    print(f"[PASS] Validated {len(translated_blocks)} bilingual blocks through {duration}")
    print(f"Output: {input_path}")


def main():
    parser = argparse.ArgumentParser(description="Validate a bilingual SRT or merge translated chunks")
    parser.add_argument("--source", "-s", required=True, help="Path to the original source SRT")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--input", "-i", help="Completed bilingual SRT to validate in place")
    mode.add_argument("--chunks-dir", "-d", help="Marked directory containing translated chunks")
    parser.add_argument("--output", "-o", help="Final bilingual SRT path for chunk merging")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output file")
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Keep marked chunks and temporary helpers after a successful merge",
    )
    args = parser.parse_args()

    try:
        if args.input:
            if args.output:
                parser.error("--output is only used with --chunks-dir")
            if args.overwrite or args.keep_workdir:
                parser.error("--overwrite and --keep-workdir are only used with --chunks-dir")
            validate_completed_file(args.source, args.input)
        else:
            if not args.output:
                parser.error("--output is required with --chunks-dir")
            merge_and_validate(
                args.source,
                args.chunks_dir,
                args.output,
                args.overwrite,
                args.keep_workdir,
            )
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    main()
