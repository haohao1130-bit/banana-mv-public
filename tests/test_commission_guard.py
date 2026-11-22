"""SRT 角色與參考圖的對應（退稿檢查已移除，只保留角色綁定解析）。"""
import unittest
from banana_mv.commission_guard import role_pictures, scene_wardrobe_schedule


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


    def test_story_specific_scene_schedule_is_removed(self):
        self.assertEqual(scene_wardrobe_schedule('USER-SPECIFIED SONG TIME 海邊 公寓', '', {}, 10), [])


if __name__ == '__main__':
    unittest.main()
