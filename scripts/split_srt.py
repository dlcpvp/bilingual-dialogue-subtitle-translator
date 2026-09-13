#!/usr/bin/env python3
"""Validate and split a standard indexed SRT file without changing cue timing."""

import argparse
import re
from pathlib import Path


TIMESTAMP_RE = re.compile(
    r"^(?P<start>\d{2,}:\d{2}:\d{2},\d{3}) --> "
    r"(?P<end>\d{2,}:\d{2}:\d{2},\d{3})$"
)
WORKDIR_MARKER = ".bilingual-srt-workdir"
WORKDIR_MARKER_CONTENT = "bilingual-dialogue-subtitle-translator\n"


def timestamp_to_milliseconds(value):
    hours, minutes, remainder = value.split(":")
    seconds, milliseconds = remainder.split(",")
    if int(minutes) > 59 or int(seconds) > 59:
        raise ValueError(f"Invalid SRT timestamp: {value}")
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        + int(milliseconds)
    )


def parse_srt(content, source_name="SRT input", expected_start=1):
    """Return ``(index, timestamp, body)`` tuples or reject malformed input."""
    normalized = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise ValueError(f"{source_name} is empty")

    raw_blocks = re.split(r"\n[ \t]*\n+", normalized.strip())
    blocks = []
    for position, raw_block in enumerate(raw_blocks, 1):
        lines = raw_block.split("\n")
        if len(lines) < 3:
            raise ValueError(f"Block {position} must contain an index, timestamp, and text")

        index_text = lines[0].strip()
        if not index_text.isdigit():
            raise ValueError(f"Block {position} has an invalid index: {lines[0]!r}")
        index = int(index_text)
        expected_index = expected_start + position - 1
        if index != expected_index:
            raise ValueError(
                f"Expected block index {expected_index}, found {index}; indexes must be consecutive"
            )

        timestamp = lines[1].strip()
        match = TIMESTAMP_RE.fullmatch(timestamp)
        if not match:
            raise ValueError(f"Block {index} has an invalid SRT timestamp: {timestamp!r}")
        if timestamp_to_milliseconds(match.group("start")) >= timestamp_to_milliseconds(match.group("end")):
            raise ValueError(f"Block {index} must end after it starts: {timestamp}")

        text_lines = [line.strip() for line in lines[2:] if line.strip()]
        if not text_lines:
            raise ValueError(f"Block {index} has no subtitle text")
        blocks.append((str(index), timestamp, "\n".join(text_lines)))

    return blocks


def read_srt(path):
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", errors="strict", newline=None) as handle:
        return parse_srt(handle.read(), str(path))


def format_source_block(block):
    index, timestamp, body = block
    normalized_text = " ".join(body.split())
    return f"{index}\n{timestamp}\n{normalized_text}"


def prepare_workdir(output_dir):
    """Create an empty, marked directory that can later be deleted safely."""
    output_dir = Path(output_dir).resolve()
    if output_dir.exists():
        if not output_dir.is_dir():
            raise ValueError(f"Output directory path is not a directory: {output_dir}")
        if any(output_dir.iterdir()):
            raise ValueError(
                f"Working directory must be new or empty to enable safe cleanup: {output_dir}"
            )
    else:
        output_dir.mkdir(parents=True)

    marker = output_dir / WORKDIR_MARKER
    with marker.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(WORKDIR_MARKER_CONTENT)
    return output_dir


def split_srt(input_path, output_dir, chunk_size=300):
    if chunk_size <= 0:
        raise ValueError("chunk size must be greater than zero")

    blocks = read_srt(input_path)
    output_dir = prepare_workdir(output_dir)

    print(f"Validated {len(blocks)} subtitle blocks from {input_path}")
    chunk_count = (len(blocks) + chunk_size - 1) // chunk_size
    print(f"Splitting into {chunk_count} chunks (maximum {chunk_size} blocks each)")

    for chunk_number, start in enumerate(range(0, len(blocks), chunk_size), 1):
        chunk = blocks[start : start + chunk_size]
        chunk_path = output_dir / f"chunk_{chunk_number}.srt"
        payload = "\n\n".join(format_source_block(block) for block in chunk) + "\n"
        with chunk_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        print(
            f"Chunk {chunk_number}: blocks {chunk[0][0]}-{chunk[-1][0]} "
            f"({len(chunk)} blocks) -> {chunk_path}"
        )

    return blocks


def main():
    parser = argparse.ArgumentParser(description="Validate or split a standard indexed SRT file")
    parser.add_argument("--input", "-i", required=True, help="Path to the source SRT file")
    parser.add_argument("--output-dir", "-o", help="Directory in which to write chunk_*.srt")
    parser.add_argument("--chunk-size", "-c", type=int, default=300, help="Maximum blocks per chunk")
    parser.add_argument("--validate-only", action="store_true", help="Validate without writing chunks")
    args = parser.parse_args()

    try:
        if args.validate_only:
            blocks = read_srt(args.input)
            print(f"[PASS] Valid standard SRT: {len(blocks)} blocks")
        else:
            if not args.output_dir:
                parser.error("--output-dir is required unless --validate-only is used")
            split_srt(args.input, args.output_dir, args.chunk_size)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    main()
