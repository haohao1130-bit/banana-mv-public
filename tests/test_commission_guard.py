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

    def test_beach_clothing_only_when_current(self):
        fixed = ('S1 = <Picture 2>\nS2 = <Picture 3>\n'
                 '海邊換成 S1 的輕便短袖與短褲、S2 的純白細繩綁帶比基尼。')
        expected = wardrobe_for_clip('她沿浪線走，兩人在淺水處嬉戲。',fixed)
        self.assertEqual(set(expected),{'S1','S2'})
        self.assertEqual(wardrobe_for_clip('S1 拿起海邊短褲，走向更衣間。',fixed),{})
        issues=check_commission(self.DEFS+'[Shot 1] A beach two-shot.\n',[],role_pictures(self.SETUP),10.0,expected,False)
        self.assertTrue(any('[Wardrobe] S1' in line for line in issues))
        self.assertTrue(any('[Wardrobe] S2' in line for line in issues))

    def test_unspecified_srt_does_not_forbid_performance(self):
        prompt = self.DEFS + '[Shot 1] <Subject 1> (S1) sings.\n'
        self.assertEqual(check_commission(prompt,[],role_pictures(self.SETUP),10.0,{},False),[])
