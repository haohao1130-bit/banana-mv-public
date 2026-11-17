"""Run: python -m unittest discover -s experiments/heretic_9b/tests -v"""
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("banana_heretic_evaluate", ROOT / "evaluate.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EvaluateTests(unittest.TestCase):
    def test_example_has_candidate_better_than_baseline(self):
        cases = module.load_jsonl(ROOT / "examples/cases.jsonl")
        baseline = module.load_jsonl(ROOT / "examples/baseline.jsonl")
        candidate = module.load_jsonl(ROOT / "examples/candidate.jsonl")
        result = module.compare(cases, baseline, candidate)
        self.assertEqual(result["baseline"]["cases_with_forbidden_hits"], 3)
        self.assertEqual(result["candidate"]["cases_with_forbidden_hits"], 0)
        self.assertEqual(result["baseline"]["filler_openings"], 3)
        self.assertEqual(result["candidate"]["filler_openings"], 0)
        self.assertEqual(result["baseline"]["json_valid"], 0)
        self.assertEqual(result["candidate"]["json_valid"], 1)

    def test_id_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            module.compare({"a": {"id": "a"}}, {"a": {"id": "a", "output": "ok"}}, {})


if __name__ == "__main__":
    unittest.main()
