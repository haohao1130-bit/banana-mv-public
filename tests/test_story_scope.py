import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from banana_mv.shoot_plan import ensure_shoot_plan
from banana_mv.scene_state import digest
import test_shoot_plan as shots
from test_unified_direction import timeline


class StoryScopeTests(unittest.TestCase):
    def test_complete_story_allocates_once_with_ending_guidance_and_no_extra_reviewer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=shots.ShootPlanTests().fixture(root)
            req['story_scope_version']=1
            (root/'requirements_attempt_03.json').write_text('{"error":"old M0 source error"}')
            model=Mock(return_value=shots.allocation())
            plan=ensure_shoot_plan(cfg,req,timeline(),images,root,model)
            self.assertEqual(model.call_count,1)
            self.assertNotIn('story_completion',plan)
            self.assertFalse((root/'story_requirements.json').exists())
            system=model.call_args.args[1]
            self.assertIn('Work backward from the mandatory ending',system)
            self.assertIn('preceding full interval',system)
            task=json.loads(model.call_args.args[2][0][1])
            self.assertNotIn('required_story_events',task)
            self.assertIn('even when cropped',task['ending_contract']['instruction'])

    def test_intact_saved_v3_plan_reused_without_rechecking_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=shots.ShootPlanTests().fixture(root)
            req['story_completion_version']=1 # Request from the removed reviewer release.
            model=Mock(return_value=shots.allocation())
            plan=ensure_shoot_plan(cfg,req,timeline(),images,root,model)
            task=json.loads(model.call_args.args[2][0][1])
            required=[{'id':'M0','source':'historical quote','event':'historical required event'}]
            legacy=dict(task,format='complete_story_shoot_briefs_v3',required_story_events=required,
                story_scope='Complete this entire story within the uploaded audio duration, even if it is cropped or ends during a chorus.')
            plan['story_completion']={'status':'passed','requirements':required}
            plan['input_sha256']=digest(legacy)
            plan['content_sha256']=digest({k:v for k,v in plan.items() if k not in ('input_sha256','content_sha256')})
            path=root/'director_plan.json';path.write_text(json.dumps(plan));before=path.read_bytes()
            self.assertEqual(ensure_shoot_plan(cfg,req,timeline(),images,root,model),plan)
            self.assertEqual(model.call_count,1);self.assertEqual(path.read_bytes(),before)

    def test_former_m0_failure_does_not_block_review_or_invoke_h3(self):
        import test_plan_review as reviews
        fixture=reviews.PlanReviewTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.req['story_completion_version']=1
        (fixture.work/'requirements_attempt_03.json').write_text('{"error":"M0 source mismatch"}')
        fixture.plan()
        self.assertEqual(fixture.model.call_count,1)
        fixture.queue.assert_not_called()
        self.assertEqual(fixture.job['status'],'plan_ready')

    def test_saved_v2_allocation_reused_without_rewriting_existing_clips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=shots.ShootPlanTests().fixture(root)
            model=Mock(return_value=shots.allocation())
            plan=ensure_shoot_plan(cfg,req,timeline(),images,root,model)
            task=json.loads(model.call_args.args[2][0][1])
            plan['input_sha256']=digest(dict(task,format='isolated_shoot_briefs_v2'))
            path=root/'director_plan.json';path.write_text(json.dumps(plan))
            before=path.read_bytes()
            model.reset_mock()
            self.assertEqual(ensure_shoot_plan(cfg,req,timeline(),images,root,model),plan)
            model.assert_not_called()
            self.assertEqual(path.read_bytes(),before)
