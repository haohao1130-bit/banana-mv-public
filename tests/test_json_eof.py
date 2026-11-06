"""Lossless recovery of complete 9B data missing only closing containers."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from PIL import Image

from banana_mv.scene_state import parse_object, SceneStateError
from banana_mv.story_plan import ensure_plan
from test_isolated_upstream import clips, shoot_orders


class JsonEofTests(unittest.TestCase):
    def test_complete_plan_missing_outer_brace(self):
        plan=shoot_orders()
        self.assertEqual(parse_object(json.dumps(plan)[:-1]),plan)

    def test_nested_containers_and_escaped_quotes_in_text(self):
        plan={'segments':[{'event':'He says "go", with {braces} and \\ a slash.'}]}
        self.assertEqual(parse_object(json.dumps(plan)[:-3]),plan)

    def test_fenced_plan_missing_outer_brace(self):
        plan=shoot_orders()
        self.assertEqual(parse_object('```json\n'+json.dumps(plan)[:-1]+'\n```'),plan)

    def test_missing_values_quotes_commas_and_mismatched_brackets_still_fail(self):
        for raw in ('{"x":', '{"x":"unfinished', '{"x":[1,',
                    '{"x":1 "y":2}', '{"x":[1}', '{"x":tru', '{"x":1e'):
            with self.subTest(raw=raw),self.assertRaises(SceneStateError):
                parse_object(raw)

    def test_complete_invalid_constants_still_fail(self):
        with self.assertRaises(SceneStateError):parse_object('{"x":NaN}')

    def test_complete_valid_json_is_unchanged(self):
        plan={'segments':[], 'ending_plan':None}
        self.assertEqual(parse_object(json.dumps(plan)),plan)

    def test_recovered_plan_still_checks_schema(self):
        req={'director_schema':3,'scene_state_version':0,'project_scope':'excerpt',
             'prompt':'test','rewrite_retries':0}
        with tempfile.TemporaryDirectory() as temp:
            images=[]
            for index in range(3):
                path=Path(temp)/f'ref{index}.png'
                Image.new('RGB',(8,8)).save(path);images.append(path)
            model=Mock(return_value=json.dumps(shoot_orders())[:-1])
            plan=ensure_plan({},req,clips(),images,Path(temp),model)
            self.assertTrue(plan['isolated_shoot_orders'])
            self.assertEqual(model.call_count,1)
            self.assertIsNone(plan['ending_plan'])
            self.assertTrue((Path(temp)/'director_plan.json').is_file())
        with tempfile.TemporaryDirectory() as temp:
            model=Mock(return_value='{"segments":[]}')
            with self.assertRaises(SceneStateError):
                ensure_plan({},req,clips(),[],Path(temp),model)
            self.assertFalse((Path(temp)/'director_plan.json').exists())


if __name__=='__main__':unittest.main()
