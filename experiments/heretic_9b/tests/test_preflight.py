"""CPU-only preflight tests; never reads the user's actual model."""
import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("banana_heretic_preflight", ROOT / "preflight.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ModelPreflightTests(unittest.TestCase):
    def test_w4a8_single_file_is_not_hf_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = pathlib.Path(tmp) / "minimax_h3_rewriter_ref2va_qwen3.5_9b_w4a8.safetensors"
            model.touch()
            result = module.inspect_model(model)
            self.assertFalse(result["compatible_layout"])
            self.assertIn("ComfyUI W4A8", result["reason"])

    def test_valid_hf_layout_is_only_potential_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "config.json").write_text(json.dumps({"model_type": "qwen3_5"}))
            (root / "tokenizer_config.json").write_text("{}")
            (root / "model-00001-of-00002.safetensors").touch()
            result = module.inspect_model(root)
            self.assertTrue(result["compatible_layout"])
            self.assertEqual(result["model_type"], "qwen3_5")
            self.assertIn("NOT verified", result["reason"])

    def test_no_config_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = module.inspect_model(pathlib.Path(tmp))
            self.assertFalse(result["compatible_layout"])

    def test_no_weights_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "config.json").write_text('{"model_type":"qwen3_5"}')
            (root / "tokenizer.json").write_text("{}")
            self.assertFalse(module.inspect_model(root)["compatible_layout"])


if __name__ == "__main__":
    unittest.main()
