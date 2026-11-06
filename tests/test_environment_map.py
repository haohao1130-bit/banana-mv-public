import unittest

from banana_mv.scene_state import SceneStateError, normalize_environment


class EnvironmentMapTests(unittest.TestCase):
    def test_text_lists_keep_each_item(self):
        result = normalize_environment({
            "active_location": "arena",
            "damaged_objects": ["破裂的欄杆", "倒下的路燈"],
            "prop_positions": ["盾牌在入口", "麥克風在舞台左側"],
        }, "arena")
        self.assertEqual(result["damaged_objects"], {
            "item_1": "破裂的欄杆", "item_2": "倒下的路燈"})
        self.assertEqual(result["prop_positions"], {
            "item_1": "盾牌在入口", "item_2": "麥克風在舞台左側"})

    def test_existing_maps_and_empty_lists(self):
        result = normalize_environment({
            "damaged_objects": {"railing": "broken"},
            "prop_positions": [],
        }, "arena")
        self.assertEqual(result["damaged_objects"], {"railing": "broken"})
        self.assertEqual(result["prop_positions"], {})

    def test_mixed_list_fails_instead_of_losing_details(self):
        with self.assertRaises(SceneStateError):
            normalize_environment({"damaged_objects": ["broken", {"x": 1}]}, "arena")


if __name__ == "__main__":
    unittest.main()
