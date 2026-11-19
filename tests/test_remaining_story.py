"""Remaining 5070 Python-slot commissions can change without touching filmed clips."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from banana_mv import remaining_story, server as app
from banana_mv.scene_state import atomic_json, digest


def make_job():
    return {
        "id": "abcdef123456", "status": "cancelled", "size": [864, 480],
        "request": {"director_schema": 6, "mode": "chain"},
        "segments": [
            {"index": 0, "start": 0., "seconds": 5., "status": "done",
             "selected_take": "original",
             "director_plan": {"handoff_version": 1, "mode": "story", "event": "已拍開場"}},
            {"index": 1, "start": 5., "seconds": 5., "status": "waiting",
             "prompt": "OLD H3 PROMPT", "prompt_id": "cancelled-id",
             "director_plan": {"handoff_version": 1, "mode": "story", "event": "原本第二幕"}},
            {"index": 2, "start": 10., "seconds": 5., "status": "waiting",
             "director_plan": {"handoff_version": 1, "mode": "story", "event": "原本結尾"}},
        ],
    }


class RemainingStoryTests(unittest.TestCase):
    def test_parse_preserves_exact_fixed_headers(self):
        job = make_job()
        text = "\n\n".join(remaining_story._header(s) + "\n" + s["director_plan"]["event"]
                           for s in job["segments"][1:])
        changed = text.replace("原本結尾", "合唱收尾")
        result = remaining_story._parse(job, 1, changed)
        self.assertEqual(result[2], "合唱收尾")
        with self.assertRaisesRegex(ValueError, "標頭"):
            remaining_story._parse(job, 1, changed.replace("10.00-15.00", "10.00-16.00"))
        with self.assertRaisesRegex(ValueError, "段數"):
            remaining_story._parse(job, 1, changed.split("=== CLIP 3")[0])
        with self.assertRaisesRegex(ValueError, "不可空白"):
            remaining_story._parse(job, 1, text.replace("原本第二幕", " "))

    def test_force_stop_from_first_pending_and_reject_holes(self):
        job = make_job()
        self.assertEqual(remaining_story._prefix(job), 1)
        job["segments"][2]["status"] = "done"
        with self.assertRaisesRegex(ValueError, "已拍"):
            remaining_story._prefix(job)
        job["status"] = "running"
        with self.assertRaisesRegex(ValueError, "停爐"):
            remaining_story._prefix(job)

    def test_update_replaces_only_pending_commissions_and_backups(self):
        job = make_job()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = {
                "version": 6, "engine": "python_owned_slots_v1",
                "source_timing": "explicit_markdown",
                "segments": [copy.deepcopy(s["director_plan"]) for s in job["segments"]],
                "input_sha256": "original-contract",
            }
            plan["content_sha256"] = digest({k: v for k, v in plan.items()
                                             if k not in ("input_sha256", "content_sha256")})
            atomic_json(root / "director_plan.json", plan)
            atomic_json(root / "status.json", job)
            old_state = (root / "status.json").read_bytes()
            old_plan = (root / "director_plan.json").read_bytes()
            def read(_):
                return json.loads((root / "status.json").read_text())
            def save(updated):
                atomic_json(root / "status.json", updated)
            lock = threading.Lock()
            with patch.object(app, "job_dir", return_value=root), \
                 patch.object(app, "read_state", side_effect=read), \
                 patch.object(app, "write_state", side_effect=save), \
                 patch.object(app, "GPU_LOCK", lock), \
                 patch.object(app, "valid_part", return_value=True), \
                 patch.object(app.backend, "load_config", return_value={}), \
                 patch("banana_mv.takes.require_idle"), \
                 patch("banana_mv.takes.take_source", return_value=root / "first.mp4"), \
                 patch.object(app, "build_workflow", side_effect=AssertionError("No H3 generation")):
                view = remaining_story.view(job["id"])
                self.assertEqual(view["from_clip"], 2)
                revised = view["text"].replace("原本第二幕", "新第二幕").replace("原本結尾", "雙人合唱")
                preview = remaining_story.preview(job["id"], view["revision"], revised)
                self.assertEqual(preview["changed_clips"], [2, 3])
                result = remaining_story.update(job["id"], view["revision"], revised)
                self.assertEqual(result["from_clip"], 2)
                updated = read(job["id"])
                self.assertEqual(updated["segments"][0], job["segments"][0])
                self.assertEqual(updated["segments"][1]["director_plan"]["event"], "新第二幕")
                self.assertTrue(updated["segments"][1]["refresh_prompt"])
                self.assertNotIn("prompt", updated["segments"][1])
                self.assertEqual(updated["status"], "interrupted")
                saved_plan = json.loads((root / "director_plan.json").read_text())
                self.assertEqual(saved_plan["segments"][2]["event"], "雙人合唱")
                self.assertEqual(saved_plan["input_sha256"], "original-contract")
                self.assertEqual(saved_plan["content_sha256"], digest(
                    {k: v for k, v in saved_plan.items() if k not in ("input_sha256", "content_sha256")}))
                backup = root / "story_revisions" / result.get("revision", updated["remaining_story_revision"])
                self.assertEqual((backup / "status.json").read_bytes(), old_state)
                self.assertEqual((backup / "director_plan.json").read_bytes(), old_plan)
                with self.assertRaisesRegex(ValueError, "更新"):
                    remaining_story.update(job["id"], view["revision"], revised)

    def test_future_event_catalog_drops_old_ending_but_keeps_commits(self):
        job = make_job()
        for seg in job["segments"][1:]:
            seg["director_plan"]["event"] = "新劇情" + str(seg["index"])
        commit = {"planned_events": ["E1"], "completed_events": ["E1"]}
        ledger = {"event_catalog": {
            "E1": {"event_id": "E1", "description": "已完成", "depends_on": []},
            "E2": {"event_id": "E2", "description": "舊結局", "depends_on": []},
        }, "commits": [commit]}
        new = remaining_story._update_ledger(ledger, job, 1, "0123456789abc")
        self.assertEqual(new["commits"], [commit])
        self.assertIn("E1", new["event_catalog"])
        self.assertNotIn("E2", new["event_catalog"])
        self.assertIn("REV01234567_C1", new["event_catalog"])
        self.assertEqual(ledger["event_catalog"]["E2"]["description"], "舊結局")


    def test_interrupted_metadata_transaction_is_rolled_back_on_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original_status = {"id": "abcdef123456", "status": "cancelled"}
            original_plan = {"version": 6, "segments": ["old"]}
            original_ledger = {"event_catalog": {"E1": "old"}}
            originals = {
                "status.json": original_status,
                "director_plan.json": original_plan,
                "scene_state.json": original_ledger,
            }
            for name, payload in originals.items():
                atomic_json(root / name, payload)
            archive = root / "story_revisions" / "crash_demo"
            archive.mkdir(parents=True)
            for name in originals:
                (archive / name).write_bytes((root / name).read_bytes())
                atomic_json(root / name, {"corrupted_by_interrupted_transaction": True})
            atomic_json(archive / "manifest.json", {"status": "backup_created"})
            with patch.object(app, "job_dir", return_value=root):
                self.assertEqual(app.read_state("abcdef123456"), original_status)
            for name, payload in originals.items():
                self.assertEqual(json.loads((root / name).read_text()), payload)
            self.assertEqual(json.loads((archive / "manifest.json").read_text())["status"],
                             "rolled_back")

    def test_new_clip_derives_event_options_without_rewriting_old_commit(self):
        from banana_mv.scene_state import clip_input
        previous = {
            "character_states": {}, "environment_states": {},
            "narrative_states": {
                "completed_events": ["E1"], "current_event": "E2",
                "pending_events": ["E2"], "reserved_final_events": [],
            }, "timeline": {},
        }
        committed = {"scene_state_out": previous, "output_sha256": digest(previous),
                     "planned_events": ["E1"], "completed_events": ["E1"],
                     "state_transitions": []}
        new_event = {"description": "新的結尾", "repeatable": False, "reserved_final": False}
        old_event = {"description": "已拍", "repeatable": False, "reserved_final": False}
        ledger = {"initial_state": previous,
                  "commits": [committed],
                  "event_catalog": {"E1": old_event, "REV_new": new_event},
                  "remaining_story_revision": "new"}
        result = clip_input(ledger, {"index": 1, "start": 5., "seconds": 5.})
        self.assertEqual(result["narrative_states"]["pending_events"], ["REV_new"])
        self.assertIsNone(result["narrative_states"]["current_event"])
        self.assertEqual(committed["scene_state_out"]["narrative_states"]["pending_events"], ["E2"])
        self.assertEqual(committed["output_sha256"], digest(previous))


if __name__ == "__main__":
    unittest.main()
