"""New projects use shoot orders instead of completed-event state ledgers."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image

from banana_mv.story_plan import validate_isolated_plan, ensure_plan
from banana_mv.scene_state import SceneStateError


def clips():
    return [
        {"index":0,"start":0.0,"seconds":10.0},
        {"index":1,"start":10.0,"seconds":10.0},
        {"index":2,"start":20.0,"seconds":10.0},
    ]


def shoot_orders():
    return {"constraints":["Only the named singer performs vocals."],
            "segments":[
                {"index":0,"event":"Tenjizi transforms into the orange hero.",
                 "mode":"story","cast":[{"id":"S1","picture":1,
                                         "appearance":"black shirt before transformation",
                                         "location":"arena"}]},
                {"index":1,"event":"The orange hero deflects the bull attack.",
                 "mode":"action","cast":[{"id":"S2","picture":2,
                                          "appearance":"orange hero suit","location":"arena"}]},
                {"index":2,"event":"The orange hero and villain trade punches.",
                 "mode":"action","cast":[{"id":"S2","picture":2,
                                          "appearance":"orange hero suit","location":"arena"},
                                         {"id":"S3","picture":3,
                                          "appearance":"horned bull armor","location":"arena"}]}],
            "closing_shot":"","ending_plan":None}


class IsolatedUpstreamTests(unittest.TestCase):
    def test_missing_change_ledger_is_not_an_error(self):
        raw=shoot_orders()
        # Simulate the old response's misleading completion metadata:
        # it has NO changes, and must not prevent any independent clip.
        raw["events"]=[{"description":"transformation","requires_change":True}]
        raw["segments"][0]["completed_indices"]=[0]
        plan=validate_isolated_plan(raw,clips(),3,{"project_scope":"excerpt"})
        self.assertTrue(plan["isolated_shoot_orders"])
        self.assertEqual(plan["requires_change"],[])
        third=plan["segments"][2]
        self.assertEqual(set(third["appearance_in"]["characters"]),{"S2","S3"})
        self.assertNotIn("S1",third["appearance_in"]["characters"])
        self.assertEqual(third["appearance_in"]["characters"]["S2"]["original_reference"],2)
        self.assertEqual(third["appearance_in"]["characters"]["S2"]["appearance_changes"],
                         ["orange hero suit"])
        self.assertNotIn("previous_planned_event",third)

    def test_actor_reference_must_exist(self):
        raw=shoot_orders()
        raw["segments"][2]["cast"][0]["picture"]=4
        with self.assertRaises(SceneStateError):
            validate_isolated_plan(raw,clips(),3,{"project_scope":"excerpt"})

    def test_whole_song_plans_once_without_events_changes(self):
        raw=shoot_orders()
        model=Mock(return_value=json.dumps(raw))
        req={"director_schema":3,"scene_state_version":0,"project_scope":"excerpt",
             "director":"auto","intensity":"high","prompt":"test story",
             "lyrics":"","story_plan":True,"rewrite_retries":0,
             "prompt_compiler_version":1}
        with tempfile.TemporaryDirectory() as temp:
            images=[]
            for i in range(3):
                p=Path(temp)/f"ref{i}.png"
                Image.new("RGB",(8,8)).save(p)
                images.append(p)
            plan=ensure_plan({},req,clips(),images,temp,model)
            self.assertEqual(model.call_count,1)
            self.assertTrue(plan["isolated_shoot_orders"])
            system=model.call_args.args[1]
            self.assertIn("ONE whole-song director",system)
            self.assertNotIn("initial_state={",system)
            self.assertEqual(len(plan["segments"]),3)
            self.assertEqual(ensure_plan({},req,clips(),images,temp,Mock(
                side_effect=AssertionError("must not replan"))),plan)


if __name__=="__main__":
    unittest.main()
