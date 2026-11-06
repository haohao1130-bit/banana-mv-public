"""Regression checks: 9B clip writer receives its assigned event, not the full history."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from banana_mv.prompt_quality import write_directed_clip


class IsolatedClipTests(unittest.TestCase):
    def test_later_clip_uses_only_current_event_and_active_cast(self):
        with tempfile.TemporaryDirectory() as tmp:
            images = [Path(tmp) / f"ref{i}.png" for i in range(1, 4)]
            for path in images:
                Image.new("RGB", (64, 64), "white").save(path)
            appearance = {
                "characters": {
                    "S2": {"original_reference": 2, "location": "port",
                           "hairstyle": "", "wearing": [], "not_wearing": [
                               {"garment_type": "jacket", "state": "removed",
                                "current_location": "floor"}],
                           "appearance_changes": [], "injuries": [], "held_props": []}
                },
                "environments": {"port": {"active_location": "a port"}},
            }
            segment = {
                "index": 1, "segment_count": 3, "seconds": 10.0,
                "direction_constraints": [],
                "director_plan": {
                    "event": "The transformed hero fights the villain in the port.",
                    "mode": "action", "subjects": ["S2"], "source_ids": ["E2"],
                    "appearance_in": appearance, "appearance_out": appearance,
                },
                # This history must never reach the visual writer.
                "previous_planned_event": "Tenjizi screams and transforms.",
            }
            req = {
                "prompt_compiler_version": 1, "rewrite_retries": 0,
                "face_identity": False, "director": "action",
                "intensity": "high",
            }
            request_parts = []

            def fake_rewrite(_cfg, _system, parts, _job):
                request_parts.append(parts)
                return "[Shot 1] <Subject 2> blocks the villain's attack and counters."

            with patch("banana_mv.services.rewrite_local", side_effect=fake_rewrite):
                prompt = write_directed_clip({}, req, segment, images, None)

            task = json.loads(request_parts[0][0][1])
            self.assertEqual(task["visual_task"], segment["director_plan"]["event"])
            self.assertEqual(task["appearance_start"]["characters"]["S2"]["connected_reference"], "<Picture 2>")
            self.assertEqual(set(task["appearance_start"]["characters"]), {"S2"})
            self.assertNotIn("not_wearing", task["appearance_start"]["characters"]["S2"])
            self.assertNotIn("removed", prompt)
            self.assertNotIn("previous_planned_event", task)
            self.assertNotIn("completed_events", task)
            self.assertNotIn("scene_state_in", task)
            self.assertNotIn("Tenjizi", prompt)
            self.assertNotIn("<Subject 1>", prompt)
            self.assertIn("<Subject 2>", prompt)

    def test_writer_instruction_forbids_backstory_replay(self):
        from banana_mv.h3_prompt import VISUAL_WRITER_SYSTEM
        self.assertIn("ENTIRE script for this clip", VISUAL_WRITER_SYSTEM)
        self.assertIn("Do not write a recap", VISUAL_WRITER_SYSTEM)


if __name__ == "__main__":
    unittest.main()
