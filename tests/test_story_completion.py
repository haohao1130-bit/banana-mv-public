import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from banana_mv.story_completion import parse_requirements,check_coverage
from banana_mv.shoot_plan import ensure_shoot_plan
from banana_mv.mv_scope import ending_contract
from banana_mv.scene_state import SceneStateError
import test_shoot_plan as fixtures

BRIEF='開場敬禮。中段閃躲反擊。最後擊倒拳王，宣布蕉彌獲勝。蕉彌站上冠軍腰帶。'
REQUIRED='''=== REQUIRE M0 BEGINNING ===
SOURCE: 開場敬禮
EVENT: The challenger salutes the champion.
=== REQUIRE M1 DEVELOPMENT ===
SOURCE: 中段閃躲反擊
EVENT: The challenger reads the attacks and counters.
=== REQUIRE M2 RESOLUTION ===
SOURCE: 最後擊倒拳王，宣布蕉彌獲勝
EVENT: The challenger knocks the champion down; the referee declares victory.
=== REQUIRE M3 FINAL_IMAGE ===
SOURCE: 蕉彌站上冠軍腰帶
EVENT: The challenger stands on the championship belt.
=== END ==='''


def rows(tail=12):
    total=60+tail
    return [dict(index=i,start=15*i,seconds=15 if i<4 else tail,song_seconds=total,segment_count=5) for i in range(5)]


def allocation(complete):
    events=['The challenger salutes the champion.','The singer performs to the crowd.',
            'The challenger reads the attacks and counters.','The singer dances with the band.',
            'The challenger knocks the champion down; the referee declares victory. The challenger stands on the championship belt.' if complete else
            'The challenger falls forward, gets up and resumes the match. Both lines keep advancing toward the final blow-off.']
    return '=== SETUP ===\n<Picture 1> is the singer; <Picture 2> is the challenger.\n'+''.join(
        f'=== CLIP {i} story ===\n{event}\n' for i,event in enumerate(events))+'=== END ==='


def audit(complete,ending_index=4):
    return '''=== COVER M0 CLIP 0 ===
The challenger salutes the champion.
=== COVER M1 CLIP 2 ===
The challenger reads the attacks and counters.
'''+(f'''=== COVER M2 CLIP {ending_index} ===
The challenger knocks the champion down; the referee declares victory.
=== COVER M3 CLIP 4 ===
The challenger stands on the championship belt.
''' if complete else '''=== MISSING M2 ===
The match merely resumes; knockout and victory are absent.
=== MISSING M3 ===
There is no belt or final image.
''')+'=== END ==='


class CompletionTests(unittest.TestCase):
    def fixture(self,root):
        images,cfg,req=fixtures.ShootPlanTests().fixture(root)
        req.update(story_completion_version=1,prompt=BRIEF,rewrite_retries=1)
        return images,cfg,req

    def test_72_second_half_story_rejected_then_whole_story_reallocated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root)
            model=Mock(side_effect=[REQUIRED,allocation(False),audit(False),allocation(True),audit(True)])
            plan=ensure_shoot_plan(cfg,req,rows(),images,root,model)
            self.assertEqual(model.call_count,5)
            self.assertEqual(plan['story_completion']['status'],'passed')
            self.assertEqual(plan['story_completion']['coverage']['M2']['clip_index'],4)
            self.assertIn('stands on the championship belt',plan['segments'][-1]['event'])
            self.assertTrue((root/'completion_audit_00.json').exists())
            again=ensure_shoot_plan(cfg,req,rows(),images,root,model)
            self.assertEqual(plan,again);self.assertEqual(model.call_count,5)
            allocator_input=model.call_args_list[1].args[2][0][1]
            self.assertIn('required_story_events',allocator_input)
            # Global checklist never enters the per-clip shooting commission.
            self.assertNotIn('story_completion',plan['segments'][0])

    def test_incomplete_final_delivery_never_saved_as_approved_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root);req['rewrite_retries']=0
            model=Mock(side_effect=[REQUIRED,allocation(False),audit(False)])
            with self.assertRaisesRegex(SceneStateError,'漏演必要事件'):
                ensure_shoot_plan(cfg,req,rows(),images,root,model)
            self.assertFalse((root/'director_plan.json').exists())

    def test_excerpt_keeps_existing_single_pass_and_no_forced_ending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root);req['project_scope']='excerpt'
            model=Mock(return_value=allocation(False))
            plan=ensure_shoot_plan(cfg,req,rows(),images,root,model)
            self.assertEqual(model.call_count,1);self.assertNotIn('story_completion',plan)

    def test_source_quotes_and_coverage_proof_cannot_be_invented(self):
        with self.assertRaisesRegex(SceneStateError,'來源引文'):
            parse_requirements(REQUIRED.replace('SOURCE: 開場敬禮','SOURCE: 不存在的故事'),BRIEF)
        required=parse_requirements(REQUIRED,BRIEF)
        local=[{'event':'The challenger salutes the champion.'},{'event':'middle'},{'event':'The challenger reads the attacks and counters.'}, {'event':'middle'}, {'event':'The match continues.'}]
        with self.assertRaisesRegex(SceneStateError,'原文證據'):
            check_coverage(audit(True),required,local,rows(),ending_contract({'project_scope':'full'},72,rows()))

    def test_tiny_tail_cannot_receive_decisive_resolution(self):
        required=parse_requirements(REQUIRED,BRIEF);timeline=rows(1)
        good_event='The challenger knocks the champion down; the referee declares victory. The challenger stands on the championship belt.'
        local=[{'event':'The challenger salutes the champion.'},{'event':'middle'},
               {'event':'The challenger reads the attacks and counters.'},{'event':good_event},{'event':good_event}]
        contract=ending_contract({'project_scope':'full'},61,timeline)
        with self.assertRaisesRegex(SceneStateError,'零星尾段'):
            check_coverage(audit(True),required,local,timeline,contract)
        checked=check_coverage(audit(True,3),required,local,timeline,contract)
        self.assertEqual(checked['coverage']['M2']['clip_index'],3)
        self.assertEqual(checked['coverage']['M3']['clip_index'],4)

    def test_worker_rejects_half_story_before_review_or_h3(self):
        import test_plan_review as reviews
        from banana_mv import server
        fixture=reviews.PlanReviewTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.req.update(story_completion_version=1,prompt=BRIEF,rewrite_retries=0)
        fixture.job.update(segments=rows(),duration=72)
        fixture.model.side_effect=[REQUIRED,allocation(False),audit(False)]
        fixture.lock.acquire()
        server.worker(fixture.job,fixture.cfg,fixture.images,fixture.root/'song.wav',fixture.root/'song.wav')
        saved=server.read_state(fixture.job['id'])
        self.assertEqual(saved['status'],'error')
        self.assertEqual(saved['error_stage'],'planning_story')
        self.assertIn('漏演必要事件',saved['error'])
        fixture.queue.assert_not_called();self.assertFalse(fixture.lock.locked())

    def test_complete_worker_persists_verified_ending_without_leaking_it_to_opening(self):
        import test_plan_review as reviews
        fixture=reviews.PlanReviewTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.req.update(story_completion_version=1,prompt=BRIEF,rewrite_retries=0)
        fixture.job.update(segments=rows(),duration=72)
        fixture.model.side_effect=[REQUIRED,allocation(True),audit(True)]
        fixture.plan()
        self.assertEqual(fixture.job['story_completion']['status'],'passed')
        self.assertNotIn('knocks',fixture.job['segments'][0]['director_plan']['event'])
        self.assertIn('stands on the championship belt',fixture.job['segments'][-1]['director_plan']['event'])
