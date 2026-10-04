"""Regression checks for cue mapping and the recorded alignment-review gate."""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from compact_srt import digest, finish, prepare, review
from split_srt import read_srt


class CompactWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="srt-regression-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.srt"
        self.output = self.root / "bilingual.srt"

    def make_task(self, english=None, **options):
        english = english or ["Because", "normal distribution", "normal distribution", "40,000 miles", "Okay?"]
        payload = []
        for index, text in enumerate(english, 1):
            seconds = index * 2
            start = f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02},000"
            end = f"{(seconds + 1) // 3600:02}:{(seconds + 1) // 60 % 60:02}:{(seconds + 1) % 60:02},000"
            payload.append(f"{index}\n{start} --> {end}\n{text}")
        self.source.write_text("\n\n".join(payload) + "\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            workdir = prepare(self.source, **options)
        self.addCleanup(shutil.rmtree, workdir, ignore_errors=True)
        return workdir

    def write_rows(self, workdir, part=1, chinese=None, corrections=None):
        blocks = read_srt(self.source)
        ranges = json.loads((workdir / "manifest.json").read_text())["ranges"]
        start, end = ranges[part - 1]
        chinese = chinese or ["因为", "正态分布", "正态分布", "40,000 英里", "好吗？"]
        rows = []
        for position in range(start, end):
            index, _, text = blocks[position]
            fields = [index, " ".join(text.split()), chinese[position]]
            if corrections and index in corrections:
                fields.append(corrections[index])
            rows.append("\t".join(fields))
        path = workdir / f"translation_{part}.tsv"
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return path

    def record_review(self, workdir, part=1):
        # Test helper models a completed human/agent review; production does not
        # auto-create approval records or claim to judge Chinese semantics.
        with contextlib.redirect_stdout(io.StringIO()):
            review(workdir, part)
        blocks = read_srt(self.source)
        start, end = json.loads((workdir / "manifest.json").read_text())["ranges"][part - 1]
        receipt = [f"SHA256\t{digest(workdir / f'translation_{part}.tsv')}"]
        receipt += [f"{index}\tOK" for index, _, _ in blocks[start:end]]
        (workdir / f"review_{part}.tsv").write_text("\n".join(receipt) + "\n", encoding="utf-8")

    def assemble(self, workdir):
        with contextlib.redirect_stdout(io.StringIO()):
            return finish(workdir, self.output, keep_workdir=True)

    def test_round_trip_preserves_short_and_repeated_cues_and_timing(self):
        workdir = self.make_task()
        self.write_rows(workdir)
        self.record_review(workdir)
        self.assemble(workdir)
        source, translated = read_srt(self.source), read_srt(self.output)
        self.assertEqual([b[:2] for b in source], [b[:2] for b in translated])
        self.assertEqual(translated[0][2], "Because\n因为")
        self.assertEqual(translated[1][2], translated[2][2])
        self.assertEqual(len(translated), 5)
        self.assertNotIn(b"\r", self.output.read_bytes())

    def test_default_batch_is_bounded_even_for_many_short_cues(self):
        workdir = self.make_task(["Okay?"] * 121)
        ranges = json.loads((workdir / "manifest.json").read_text())["ranges"]
        self.assertEqual(ranges, [[0, 60], [60, 120], [120, 121]])

    def test_all_batches_need_review_and_corrected_english_keeps_original_anchor(self):
        workdir = self.make_task(max_cues=2)
        for part in (1, 2, 3):
            self.write_rows(workdir, part=part, corrections={"4": "40,000 miles."})
        self.record_review(workdir, 1)
        with self.assertRaisesRegex(ValueError, "Missing alignment review for task 2"):
            self.assemble(workdir)
        self.assertFalse(self.output.exists())
        for part in (2, 3):
            self.record_review(workdir, part)
        with contextlib.redirect_stdout(io.StringIO()):
            finish(workdir, self.output)
        self.assertEqual(read_srt(self.output)[3][2], "40,000 miles.\n40,000 英里")
        self.assertIn("40,000 miles\n", self.source.read_text())
        self.assertFalse(workdir.exists())

    def test_character_limit_does_not_split_a_single_cue(self):
        workdir = self.make_task(["A long fragment", "Because", "Okay?"], max_chars=10)
        ranges = json.loads((workdir / "manifest.json").read_text())["ranges"]
        self.assertEqual(ranges, [[0, 1], [1, 2], [2, 3]])

    def test_source_anchor_rejects_shift_despite_correct_ids_and_count(self):
        workdir = self.make_task()
        path = self.write_rows(workdir)
        path.write_text(path.read_text().replace("1\tBecause\t", "1\tnormal distribution\t"))
        with self.assertRaisesRegex(ValueError, "source English does not match ID 1"):
            self.assemble(workdir)
        self.assertFalse(self.output.exists())

    def test_missing_review_blocks_export_and_keeps_draft(self):
        workdir = self.make_task()
        path = self.write_rows(workdir)
        with self.assertRaisesRegex(ValueError, "Missing alignment review"):
            self.assemble(workdir)
        self.assertTrue(path.is_file())
        self.assertFalse(self.output.exists())

    def test_review_becomes_stale_after_translation_edit(self):
        workdir = self.make_task()
        path = self.write_rows(workdir)
        self.record_review(workdir)
        path.write_text(path.read_text().replace("好吗？", "好吧？"))
        with self.assertRaisesRegex(ValueError, "stale or invalid translation SHA256"):
            self.assemble(workdir)
        self.assertFalse(self.output.exists())
        self.record_review(workdir)
        self.assemble(workdir)
        self.assertIn("好吧？", self.output.read_text())

    def test_partial_review_is_insufficient(self):
        workdir = self.make_task()
        self.write_rows(workdir)
        self.record_review(workdir)
        path = workdir / "review_1.tsv"
        path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
        with self.assertRaisesRegex(ValueError, "every target cue"):
            self.assemble(workdir)

    def test_review_shows_corrections_and_both_batch_boundaries(self):
        workdir = self.make_task(max_cues=2)
        self.write_rows(workdir, part=2, corrections={"4": "40,000 miles."})
        with contextlib.redirect_stdout(io.StringIO()):
            path = review(workdir, 2)
        text = path.read_text()
        self.assertIn("ID 2 |", text)
        self.assertIn("ID 5 |", text)
        self.assertIn("SOURCE: 40,000 miles\nENGLISH: 40,000 miles.\nCHINESE: 40,000 英里", text)
        self.assertFalse((workdir / "review_2.tsv").exists())

    def test_semantic_drift_is_exposed_for_review_without_auto_approval(self):
        workdir = self.make_task()
        self.write_rows(workdir, chinese=["正态分布", "正态分布", "40,000 英里", "好吗？", "因为"])
        with contextlib.redirect_stdout(io.StringIO()):
            path = review(workdir, 1)
        self.assertIn("ENGLISH: Because\nCHINESE: 正态分布", path.read_text())
        with self.assertRaisesRegex(ValueError, "Missing alignment review"):
            self.assemble(workdir)

    def test_placeholder_cannot_pad_a_skipped_cue(self):
        workdir = self.make_task()
        self.write_rows(workdir, chinese=["因为", "正态分布", "…", "40,000 英里", "好吗？"])
        with self.assertRaisesRegex(ValueError, "placeholder translation at ID 3"):
            self.assemble(workdir)

    def test_truncated_manifest_cannot_omit_last_cues(self):
        workdir = self.make_task(max_cues=2)
        path = workdir / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["ranges"].pop()
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "do not cover every source cue"):
            self.assemble(workdir)

    def test_source_changes_invalidate_preparation(self):
        workdir = self.make_task()
        self.write_rows(workdir)
        self.source.write_text(self.source.read_text().replace("Because", "But"))
        with self.assertRaisesRegex(ValueError, "Source changed"):
            self.assemble(workdir)

    def test_old_workdir_requires_new_preparation(self):
        workdir = self.make_task()
        path = workdir / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest.pop("version")
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Old translation draft format"):
            self.assemble(workdir)


if __name__ == "__main__":
    unittest.main()
