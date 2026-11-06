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
    def test_full_work_ending_survives_actor_end_appearance_and_location(self):
        from banana_mv.mv_scope import clip_ending
        raw=shoot_orders()
        expected={'start_time':20,'resolved_by':28,'resolution':'Resolve the contest and hold the final image.'}
        raw.update(ending_plan=expected,closing_shot='Hold the hero image.')
        raw['segments'][-1]['cast'][-1].update(end_appearance='changed armor',end_location='exit')
        req={'project_scope':'full'}
        plan=validate_isolated_plan(raw,clips(),3,req)
        self.assertEqual(plan['ending_plan'],expected)
        seg=dict(clips()[-1],song_seconds=30,segment_count=3,direction_ending_plan=plan['ending_plan'],
                 direction_ending_contract=plan['ending_contract'])
        ending=clip_ending(req,seg)
        self.assertEqual(ending['local_resolution_by'],8)
        self.assertEqual(ending['resolution'],expected['resolution'])
        self.assertEqual(plan['segments'][-1]['appearance_out']['characters']['S3']['location'],'exit')

    def test_excerpt_keeps_null_ending_with_multiple_cast_and_changes(self):
        raw=shoot_orders();raw['segments'][-1]['cast'][-1]['end_appearance']='changed armor'
        plan=validate_isolated_plan(raw,clips(),3,{'project_scope':'excerpt'})
        self.assertIsNone(plan['ending_plan'])

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
            self.assertIsNone(plan['ending_plan'])
            system=model.call_args.args[1]
            self.assertIn("ONE whole-song director",system)
            self.assertNotIn("initial_state={",system)
            self.assertEqual(len(plan["segments"]),3)
            self.assertEqual(ensure_plan({},req,clips(),images,temp,Mock(
                side_effect=AssertionError("must not replan"))),plan)

    def test_invalid_cached_ending_is_reported_without_silent_replanning(self):
        from banana_mv.scene_state import digest
        req={'director_schema':3,'scene_state_version':0,'project_scope':'excerpt',
             'prompt':'same brief','rewrite_retries':0}
        with tempfile.TemporaryDirectory() as temp:
            raw=shoot_orders()
            for row in raw['segments']:
                for actor in row['cast']:actor['picture']=None
            plan=ensure_plan({},req,clips(),[],temp,Mock(return_value=json.dumps(raw)))
            plan['ending_plan']='old corrupted costume text'
            plan['content_sha256']=digest({k:v for k,v in plan.items() if k not in ('input_sha256','content_sha256')})
            (Path(temp)/'director_plan.json').write_text(json.dumps(plan))
            no_model=Mock(side_effect=AssertionError('do not overwrite saved projects'))
            with self.assertRaisesRegex(SceneStateError,'結尾資料無效'):
                ensure_plan({},req,clips(),[],temp,no_model)
            no_model.assert_not_called()

    def test_clip_local_transition_uses_both_fixed_original_refs(self):
        raw=shoot_orders()
        raw['segments'][0]['cast'].append({
            'id':'S2','picture':2,'appearance':'new outfit','location':'arena',
            'visibility':'closing'})
        raw['segments'][0]['cast'][0]['visibility']='opening'
        raw['segments'][0]['transitions']=[{'from':'S1','to':'S2'}]
        raw['segments'][0]['cast'][0]['end_appearance']='different shirt'
        plan=validate_isolated_plan(raw,clips(),3,{'project_scope':'excerpt'})
        first=plan['segments'][0]
        self.assertEqual(first['subjects'],['S1','S2'])
        self.assertEqual(first['transitions'],[{'from':'S1','to':'S2'}])
        self.assertEqual(first['cast_visibility'],{'S1':'opening','S2':'closing'})
        self.assertEqual(first['appearance_in']['characters']['S1']['original_reference'],1)
        self.assertEqual(first['appearance_in']['characters']['S2']['original_reference'],2)
        self.assertEqual(first['appearance_out']['characters']['S1']['appearance_changes'],['different shirt'])
        self.assertEqual(plan['segments'][1]['appearance_in']['characters']['S2']['original_reference'],2)
        self.assertNotIn('S1',plan['segments'][1]['appearance_in']['characters'])

    def test_actor_reference_never_shifts_with_cast_position(self):
        raw=shoot_orders()
        raw['segments'][2]['cast'][0]['picture']=1
        with self.assertRaisesRegex(SceneStateError,'不同原始圖片'):
            validate_isolated_plan(raw,clips(),3,{'project_scope':'excerpt'})
        raw=shoot_orders()
        raw['segments'][0]['transitions']=[{'from':'S1','to':'S2'}]
        with self.assertRaisesRegex(SceneStateError,'當段兩個不同'):
            validate_isolated_plan(raw,clips(),3,{'project_scope':'excerpt'})


if __name__=="__main__":
    unittest.main()

