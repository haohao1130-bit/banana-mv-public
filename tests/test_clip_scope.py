import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from banana_mv.prompt_quality import (clip_scope, ending_excerpt, enforce_clip_scope)


class ClipScopeTests(unittest.TestCase):
    def test_ending_is_copied_from_user_and_not_appended_to_early_generation(self):
        brief='【人物】\n參考圖人物分別演唱與拳擊。\n【終局】\n拳套飛向裁判。\n最後硬切回舞台，主唱唱完收尾。\n【限制】\n角色不得交換。'
        ending=ending_excerpt(brief)
        self.assertIn('最後硬切回舞台',ending)
        self.assertNotIn('角色不得交換',ending)
        early=clip_scope({'index':0,'segment_count':4,'seconds':15},brief)
        final=clip_scope({'index':3,'segment_count':4,'seconds':14.67},brief)
        self.assertIn('NON-FINAL WINDOW',early)
        self.assertNotIn('拳套飛向裁判',early)
        self.assertIn('Do not output the whole-song storyboard',early)
        self.assertIn(ending,final)
        self.assertIn('terminal shot',final)
        self.assertIn('14.670000s',final)
        text=enforce_clip_scope('prompt',final)
        self.assertEqual(enforce_clip_scope(text,final),text)

    def test_no_concert_ending_is_invented_for_a_different_story(self):
        brief='最後一鏡停留在雨中街道的背影。'
        scope=clip_scope({'seconds':10},brief)
        self.assertIn(brief,scope)
        self.assertNotIn('concert',scope)

    def test_first_and_last_segment_at_real_59_67_seconds_have_different_scope(self):
        from PIL import Image
        from banana_mv import server
        from banana_mv.core import segments
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'ref.png';Image.new('RGB',(32,32)).save(image)
            guide=root/'guide.md';guide.write_text('H3 guide')
            cfg={'guides':{'ref':str(guide)}}
            brief='@圖片1 為主唱，@圖片2 為拳手。\n【終局】\n拳套飛向裁判，最後硬切回 @圖片1 唱完收尾。\n【限制】\n角色不交換。'
            req={'prompt':brief,'rewrite':True,'optimizer_version':1,'director_version':2,'director':'auto',
                 'intensity':'high','face_identity':False}
            timeline=segments(59.67,15)
            for seg in timeline:seg.update(segment_count=4,song_seconds=59.67)
            for final in (False,True):
                seg=timeline[-1] if final else timeline[0]
                seg['director_plan']={'mode':'performance' if final else 'action',
                                      'event':'Return to the performance to finish the song.' if final else 'Continue the ongoing boxing exchange.'}
                rewritten='subject_definitions: performers from <Picture 1> and <Picture 2>.\nsummary: '+seg['director_plan']['event']
                rewrite=Mock(return_value=rewritten)
                with patch.object(server.backend,'rewrite_local',rewrite):
                    result=server.local_prompt(cfg,req,seg,[image,image],None)
                first_input=rewrite.call_args_list[0].args[2][0][1]
                system=rewrite.call_args_list[0].args[1]
                self.assertEqual(first_input.count('WHOLE-SONG USER REFERENCE — NOT THE CURRENT CLIP SCRIPT'),1)
                self.assertIn('OUTPUT SCOPE OVERRIDE',system)
                if final:
                    self.assertIn('最後硬切回 <Picture 1> 唱完收尾',result)
                    self.assertIn(f'Target visible duration: {seg["seconds"]:.6f}',first_input)
                else:
                    self.assertNotIn('拳套飛向裁判',result)
                    self.assertIn('NON-FINAL WINDOW',result)
                self.assertEqual(req['prompt'],brief)
                self.assertEqual(rewrite.call_count,1)
