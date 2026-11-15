"""FL2VA experiment never reuses the multi-reference Ref2VA graph."""
import unittest
from banana_mv.fl2va_experiment import build_fl2va_graph, PROFILES

class FL2VAExperimentTests(unittest.TestCase):
    def make(self,**kwargs):
        return build_fl2va_graph(first_frame="first.png",audio="slice.wav",
                 prompt="An adult performer walks forward through sunlight.",**kwargs)

    def test_turbo8_is_firstframe_conditioning_only(self):
        graph=self.make()
        self.assertEqual(graph["1"]["inputs"]["unet_name"],PROFILES["turbo8"][0])
        self.assertEqual(graph["12"]["inputs"]["steps"],8)
        cond=graph["7"]["inputs"]
        self.assertEqual(cond["task_type"],"I2VA")
        self.assertEqual(cond["first_frame"],["5",0])
        self.assertEqual(cond["audio_mode"],"lock_source")
        self.assertFalse(cond["add_source_as_reference"])
        self.assertEqual(cond["prompt_primary_audio_ordinal"],0)
        self.assertFalse(any(x.startswith("ref_images.") for x in cond))
        self.assertFalse(any(x.startswith("ref_audios.") for x in cond))
        self.assertNotIn("motion_repair",graph)
        self.assertNotIn("sparse_attention",graph)
        self.assertIn("attention_backend",graph)

    def test_baseline_uses_twenty_steps_without_unmatched_lora(self):
        graph=self.make(profile="base")
        self.assertEqual(graph["1"]["inputs"]["unet_name"],PROFILES["base"][0])
        self.assertEqual(graph["12"]["inputs"]["steps"],20)
        self.assertFalse(any(node["class_type"]=="LoraLoaderModelOnly"
                             for node in graph.values()))

    def test_first_last_frame_is_fl2va_not_hybrid(self):
        graph=self.make(last_frame="end.png")
        cond=graph["7"]["inputs"]
        self.assertEqual(cond["task_type"],"FL2VA")
        self.assertEqual(cond["last_frame"],["last_frame_load",0])
        self.assertNotIn("ref_images.ref_image_0",cond)
        self.assertFalse(cond["add_source_as_reference"])

    def test_ref2va_tags_and_bad_dimensions_are_rejected(self):
        for s in ("", "<Audio 1> sings.", "<Picture 2> enters."):
            with self.subTest(prompt=s),self.assertRaises(ValueError):
                build_fl2va_graph(first_frame="a.png",audio="b.wav",prompt=s)
        for seconds in (0,3.5,17,float("nan")):
            with self.subTest(seconds=seconds),self.assertRaises(ValueError):
                self.make(seconds=seconds)
        with self.assertRaises(ValueError):
            self.make(width=1280,height=720+8)
