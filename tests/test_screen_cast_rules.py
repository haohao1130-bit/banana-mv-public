"""Regression: source chapter cast labels control 9B and H3 visuals."""
import unittest

from banana_mv.director_shoot import _free_commission
from banana_mv.locked_shoot import _native, clip_screen_cast_rule


FIRST = (
    "PYTHON-OWNED CURRENT EVENT — scene "
    "00:00.000–00:10.000｜第01段｜入鏡：S2 白素貞｜不入鏡：S1 蕉大師（全段）\n"
    "- @0.000s 暴雨雷峰塔；白素貞沿石階前進。"
)
SECOND = (
    "PYTHON-OWNED CURRENT EVENT — scene "
    "00:10.000–00:20.000｜第02段｜入鏡：S2 白素貞（00:10.000起）、"
    "S1 蕉大師（00:17.813首次入鏡）｜S1 在00:17.813之前不入鏡\n"
    "- @7.813s 蕉大師第一次出現在古寺內。"
)
BOTH = (
    "PYTHON-OWNED CURRENT EVENT — scene "
    "00:20.000–00:30.000｜第03段｜入鏡：S1 蕉大師、S2 白素貞\n"
    "- @2.800s 兩人開始對話。"
)
PICS = {"S1": "<Picture 1>", "S2": "<Picture 2>"}


class TestScreenCastRules(unittest.TestCase):
    def test_first_clip_omits_unseen_monk(self):
        rule = clip_screen_cast_rule(FIRST)
        self.assertIn("CURRENT ON-SCREEN CAST", rule)
        self.assertIn("S2 白素貞", rule)
        self.assertIn("MUST STAY OFF SCREEN: S1 蕉大師", rule)
        self.assertIn("silhouette", rule)

    def test_second_clip_entrance_gate(self):
        rule = clip_screen_cast_rule(SECOND)
        self.assertIn("FIRST APPEARANCE GATE", rule)
        self.assertIn("S1 在00:17.813之前不入鏡", rule)

    def test_third_clip_both_visible(self):
        rule = clip_screen_cast_rule(BOTH)
        self.assertIn("S1 蕉大師、S2 白素貞", rule)
        self.assertNotIn("MUST STAY OFF SCREEN", rule)

    def test_legacy_prompt_unchanged(self):
        self.assertEqual(clip_screen_cast_rule("Two people perform."), "")

    def test_clip_commission_has_screen_permission(self):
        commission = _free_commission(
            {"intensity": "high"}, {"seconds": 10.0}, FIRST, PICS,
            {}, [], continuity=False,
        )
        self.assertIn("PYTHON FILMING AUTHORITY", commission)
        self.assertIn("MUST STAY OFF SCREEN: S1 蕉大師", commission)

    def test_h3_prompt_keeps_six_sections_and_rule(self):
        slots = [{
            "number": 1, "start": 0.0, "end": 10.0,
            "rows": ["0.000–10.000s: No assigned visible lip-sync; "
                     "use physical acting and reaction."],
        }]
        native = _native(
            {1: "白素貞在雷峰塔的雨夜前進。"}, slots,
            PICS, {}, False, FIRST, 2,
        )
        for section in (
            "subject_definitions:", "summary:", "retention_analysis:",
            "detailed_description:", "overall_soundscape:",
            "non_diegetic_music:",
        ):
            self.assertIn(section, native)
        self.assertEqual(native.count("MUST STAY OFF SCREEN: S1 蕉大師"), 2)


if __name__ == "__main__":
    unittest.main()
