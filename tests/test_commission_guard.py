"""Regression of clip-local singer authority and beach wardrobe corrections."""
import unittest
from banana_mv.commission_guard import check_commission, role_pictures, wardrobe_for_clip


class CommissionGuardTests(unittest.TestCase):
    SETUP = 'S1 = <Picture 2>, male singer\nS2 = <Picture 3>, female singer\n'
    DEFS = ('subject_definitions:\n'
            '<Subject 1> is the male singer S1 from <Picture 2>, wearing a dark hoodie and cargo pants.\n'
            '<Subject 2> is the female singer S2 from <Picture 3>, wearing a cream cardigan and denim skirt.\n'
            'summary:\nA beach music video.\n'
            'retention_analysis:\n'
            '<Subject 1> retains his hoodie and cargo pants.\n'
            '<Subject 2> retains her cardigan and denim skirt.\n'
            'detailed_description:\n')
    def test_wrong_singer_and_duet_detected(self):
        cues = [
            {'clip_start':0.0,'clip_end':5.24,'subjects':['S1']},
            {'clip_start':5.24,'clip_end':7.087,'subjects':['S2']},
            {'clip_start':7.087,'clip_end':10.0,'subjects':['S1']},
        ]
        prompt = self.DEFS + ('[Shot 1] <Subject 2> (S2) sings the opening phrase.\n'
                               '[Shot 2] At 00:05.240, <Subject 1> (S1) begins singing.\n'
                               '[Shot 3] At 00:07.087, <Subject 1> (S1) sings correctly.\n'
                               'overall_soundscape:\nOriginal track.')
        issues = check_commission(prompt,cues,role_pictures(self.SETUP),10.0,{},True)
        self.assertGreaterEqual(len(issues),2)
        self.assertTrue(any('[Shot 1]' in line for line in issues))
        self.assertTrue(any('[Shot 2]' in line for line in issues))
        duet = self.DEFS + ('[Shot 1] <Subject 1> (S1) sings.\n'
                            '[Shot 2] At 00:05.240, Both sing the duet line together.\n')
        self.assertTrue(any('S1' in line for line in check_commission(
            duet,cues,role_pictures(self.SETUP),10.0,{},True)))

    def test_silent_reaction_is_not_an_error(self):
        cues = [{'clip_start':0.0,'clip_end':10.0,'subjects':['S2']}]
        prompt = self.DEFS + ('[Shot 1] <Subject 1> watches <Subject 2> (S2) sing while he smiles.\n'
                              '[Shot 2] At 00:04.000, <Subject 1> watches her sing without speaking.\n')
        self.assertEqual(check_commission(prompt,cues,role_pictures(self.SETUP),10.0,{},True),[])


    def test_reverse_picture_singer_bindings_match_real_one_click_brief(self):
        fixed = ('<Picture 1>＝蕉大師，S1，男性角色\n'
                 '<Picture 2>＝白素貞，S2，女性角色\n')
        expected = {'S1':'<Picture 1>','S2':'<Picture 2>'}
        self.assertEqual(role_pictures(fixed),expected)
        self.assertEqual(role_pictures(
            '@圖片1＝蕉大師，S1\n@圖片2＝白素貞，S2\n'),expected)
        self.assertEqual(role_pictures('S1 = <Picture 2>\nS2 = <Picture 3>\n'),
                         {'S1':'<Picture 2>','S2':'<Picture 3>'})
        self.assertEqual(role_pictures('<Picture 1>＝和尚\n<Picture 2>＝白蛇\n'),{})

    def test_long_form_subject_to_picture_and_srt_links(self):
        director = (
            '02｜SUBJECT DEFINITIONS\n'
            'Subject 1｜蕉大師\n'
            'Use @圖片1 as the exclusive visual identity reference.\n'
            'A middle-aged bald monk.\n'
            'Subject 2｜白素貞\n'
            'Use @圖片2 as the exclusive visual identity reference.\n'
            'An adult white snake woman.\n'
            'Subject 3｜大乘蕉宗神社\n'
            'The stormy main environment, not an actor.\n'
            '04｜AUDIO AND SRT LOCK\n'
            '[S1] = Subject 1 蕉大師\n'
            '[S2] = Subject 2 白素貞\n'
        )
        expected={'S1':'<Picture 1>','S2':'<Picture 2>'}
        self.assertEqual(role_pictures(director),expected)
        from banana_mv.core import map_image_mentions
        self.assertEqual(role_pictures(map_image_mentions(director,2)),expected)
        self.assertEqual(role_pictures(director.replace('[S2] = Subject 2 白素貞','')), 
                         {'S1':'<Picture 1>'})
        self.assertEqual(role_pictures(director.replace('Use @圖片2 as the exclusive visual identity reference.','')),
                         {'S1':'<Picture 1>'})
        # Never infer a singer just because Subject 3 has a scene description.
        self.assertNotIn('S3',role_pictures(director))

    def test_spoken_and_rap_vocals_cannot_be_stolen_from_srt_owner(self):
        setup = '<Picture 1>＝蕉大師，S1\n<Picture 2>＝白素貞，S2\n'
        defs = ('subject_definitions:\n'
                '<Subject 1> is 蕉大師 (S1) from <Picture 1>, an adult male monk.\n'
                '<Subject 2> is 白素貞 (S2) from <Picture 2>, an adult female singer.\n'
                'summary:\nThe stormy plaza.\n'
                'retention_analysis:\nThe cast stays fixed.\n'
                'detailed_description:\n')
        cues=[{'clip_start':0.0,'clip_end':10.0,'subjects':['S2']}]
        wrong = defs + (
            '[Shot 1] At 00:00.000, <Subject 1> (S1) raps forcefully while <Subject 2> reacts.\n'
            '[Shot 2] At 00:04.000, <Subject 1> (S1) begins rapping over the original audio.\n'
            '[Shot 3] At 00:07.000, <Subject 1> (S1) speaks in a low voice.\n'
            '[Shot 4] At 00:09.000, <Subject 1> (S1) performs spoken delivery.\n'
        )
        errors=check_commission(wrong,cues,role_pictures(setup),10.0,{},True)
        self.assertTrue(any('[Shot 1]' in x for x in errors),errors)
        self.assertTrue(any('[Shot 2]' in x for x in errors),errors)
        self.assertTrue(any('[Shot 3]' in x for x in errors),errors)
        self.assertTrue(any('[Shot 4]' in x for x in errors),errors)
        okay = defs + ('[Shot 1] At 00:00.000, <Subject 1> watches '
                       '<Subject 2> (S2) rapping; he plays the wooden fish silently.\n')
        self.assertEqual(check_commission(okay,cues,role_pictures(setup),10.0,{},True),[])

    def test_beach_clothing_only_when_current(self):
        fixed = ('S1 = <Picture 2>\nS2 = <Picture 3>\n'
                 '海邊換成 S1 的輕便短袖與短褲、S2 的純白細繩綁帶比基尼。')
        expected = wardrobe_for_clip('她沿浪線走，兩人在淺水處嬉戲。',fixed)
        self.assertEqual(set(expected),{'S1','S2'})
        self.assertEqual(wardrobe_for_clip('S1 拿起海邊短褲，走向更衣間。',fixed),{})
        issues=check_commission(self.DEFS+'[Shot 1] A beach two-shot.\n',[],role_pictures(self.SETUP),10.0,expected,False)
        self.assertTrue(any('[Wardrobe] S1' in line for line in issues))
        self.assertTrue(any('[Wardrobe] S2' in line for line in issues))

    def test_valid_beach_outfit_passes(self):
        fixed = ('S1 = <Picture 2>\nS2 = <Picture 3>\n'
                 '海邊換成 S1 的輕便短袖與短褲、S2 的純白細繩綁帶比基尼。')
        appearance = ('subject_definitions:\n'
                      '<Subject 1> is the male singer S1 from <Picture 2> in a short-sleeve t-shirt and shorts.\n'
                      '<Subject 2> is the female singer S2 from <Picture 3> in a pure white tie-string bikini.\n'
                      'summary:\nA sunny beach.\n'
                      'retention_analysis:\n'
                      '<Subject 1> retains his short-sleeve t-shirt and shorts.\n'
                      '<Subject 2> retains her pure white tie-string bikini.\n'
                      'detailed_description:\n[Shot 1] A reaction shot.\n')
        self.assertEqual(check_commission(appearance,[],role_pictures(self.SETUP),10,
            wardrobe_for_clip('兩人到了海邊步道。',fixed),False),[])

    def test_mentioning_seawater_does_not_trigger_beach_wardrobe(self):
        from banana_mv.commission_guard import scene_is_beach
        mention='場景：白天公寓工作室與客廳。\n她唱「我都快忘記海水到底有多甜」。'
        self.assertFalse(scene_is_beach(mention))
        self.assertEqual(wardrobe_for_clip(mention,
            'S1 穿短袖短褲、S2 穿純白細繩綁帶比基尼'),{})
        self.assertTrue(scene_is_beach('場景：白天海邊，兩人沿浪線玩水。'))

    def test_unspecified_srt_does_not_forbid_performance(self):
        prompt = self.DEFS + '[Shot 1] <Subject 1> (S1) sings.\n'
        self.assertEqual(check_commission(prompt,[],role_pictures(self.SETUP),10.0,{},False),[])

    def test_srt_without_a_clip_local_subject_allows_authored_singing(self):
        from banana_mv.lyrics_reference import excerpt, vocal_timeline

        prompt = self.DEFS + '[Shot 1] <Subject 1> (S1) sings.\n'
        clip = {'start': 0, 'seconds': 10}
        cases = [
            {'start': 0, 'end': 8, 'text': '有時間碼的歌詞'},
            {'start': 0, 'end': 8, 'text': '[女聲] 有聲部的歌詞'},
            {'start': 10, 'end': 15, 'text': '[S2] 下一段才標歌手'},
            {'start': 0, 'end': 8, 'text': '[S2] 本段明確標了另一位歌手'},
        ]
        for cue, expected_error in zip(cases, (False, False, False, True)):
            with self.subTest(cue=cue):
                timeline = vocal_timeline(excerpt({'srt_cues': [cue]}, clip))
                errors = check_commission(prompt, timeline, role_pictures(self.SETUP), 10.0, {}, True)
                self.assertEqual(bool(errors), expected_error, errors)

    def test_untagged_shot_in_partly_tagged_clip_allows_natural_lip_sync(self):
        cues = [{'clip_start': 0, 'clip_end': 4, 'subjects': ['S1']}]
        prompt = self.DEFS + ('[Shot 1] <Subject 1> (S1) sings.\n'
                              '[Shot 2] At 00:05.000, <Subject 1> (S1) continues singing.\n')
        self.assertEqual(check_commission(prompt, cues, role_pictures(self.SETUP), 10, {}, True), [])

    def test_eight_role_tags_follow_explicit_cast_binding(self):
        from banana_mv.lyrics_reference import vocal_timeline

        fixed = ('Subject 3｜角色甲\nUse @圖片8 as visual reference.\n'
                 '[S4] = Subject 3\nS8 = <Picture 2>')
        self.assertEqual(role_pictures(fixed), {'S4': '<Picture 8>', 'S8': '<Picture 2>'})
        timeline = vocal_timeline([{'clip_start': 0, 'clip_end': 4, 'text': '[S8 + S4] 歌詞'}])
        self.assertEqual(timeline[0]['subjects'], ['S8', 'S4'])
        prompt = ('subject_definitions:\n<Subject 3> is the actor from <Picture 8>.\n'
                  'detailed_description:\n[Shot 1] <Subject 3> lip-syncs.')
        self.assertEqual(check_commission(prompt, timeline, role_pictures(fixed), 4, {}, True), [])
        timeline[0]['subjects'] = ['S8']
        self.assertTrue(check_commission(prompt, timeline, role_pictures(fixed), 4, {}, True))
