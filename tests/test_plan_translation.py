import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from banana_mv.plan_translation import checked,translate_plan
import test_plan_review as reviews
from banana_mv import server
import test_shoot_plan as shots


class TranslationTests(unittest.TestCase):
    def fixture(self):
        return {'plan_preview_setup':'<Picture 1> is the singer. <Picture 2> is the challenger.',
                'segments':[{'index':0,'director_plan':{'event':'<Picture 2> dodges 2 punches; <Audio 1> stays unchanged.'}},
                            {'index':1,'director_plan':{'event':'<Picture 1> sings; the challenger wins only here.'}}]}

    def test_translation_is_separate_cached_and_never_rewrites_english(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=self.fixture();original=copy.deepcopy(job)
            model=Mock(side_effect=lambda cfg,system,parts,uid:'繁中審閱：'+parts[0][1].split('<SOURCE>\n')[1].split('\n</SOURCE>')[0])
            result=translate_plan(job,tmp,{},model,'english-rev')
            self.assertEqual(job,original)
            self.assertEqual(result['status'],'ready');self.assertEqual(model.call_count,3)
            self.assertEqual(set(result['blocks']),{'setup','0','1'})
            self.assertEqual(translate_plan(job,tmp,{},model,'english-rev'),result)
            self.assertEqual(model.call_count,3)
            job['segments'][0]['director_plan']['event']+=' The glove drops.'
            translate_plan(job,tmp,{},model,'english-rev-2');self.assertEqual(model.call_count,6)

    def test_reference_number_or_missing_chinese_is_rejected(self):
        source='<Picture 2> dodges 2 punches with <Audio 1>.'
        for text in ('<Picture 1> 閃過 2 拳，<Audio 1>。','<Picture 2> 閃過 3 拳，<Audio 1>。',source):
            with self.subTest(text=text),self.assertRaises(ValueError):checked(text,source)

    def test_cancel_and_failed_translation_never_save_partial_ready_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            model=Mock(return_value='中文但漏掉圖片編號')
            with self.assertRaises(ValueError):translate_plan(self.fixture(),tmp,{},model,'rev')
            self.assertEqual(model.call_count,2)
            self.assertFalse((Path(tmp)/'plan_review_zh.json').exists())
            with self.assertRaises(InterruptedError):
                translate_plan(self.fixture(),tmp,{},model,'rev',cancelled=lambda:True)


class ReviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=reviews.PlanReviewTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_review_shows_original_plan_without_automatic_translation(self):
        # 409e4a1 起審稿直接看原稿，不再自動翻譯（舊的 preview_zh 會被忽略）。
        f=self.fixture;f.req['preview_zh']=True
        translator=Mock(side_effect=AssertionError('review must not translate'))
        with patch('banana_mv.plan_translation.translate_plan',translator):f.plan()
        translator.assert_not_called()
        self.assertNotIn('plan_translation',f.job)
        self.assertEqual(f.job['status'],'plan_ready')
        self.assertEqual(server.plan_revision(f.job),f.job['plan_revision'])
        self.assertTrue(f.job['plan_preview_setup']);f.queue.assert_not_called()
        writer=Mock(return_value=shots.native_prompt(0))
        with patch.object(server.backend,'rewrite_local',writer):
            server.local_prompt(f.cfg,f.req,f.job['segments'][0],f.images,None)
        sent='\n'.join(value for kind,value in writer.call_args.args[2] if kind=='text')
        self.assertIn('HUMAN_OPENING',sent)
