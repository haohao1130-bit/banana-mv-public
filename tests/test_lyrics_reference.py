import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from banana_mv.lyrics_reference import parse_srt,normalize_references,excerpt,clip_reference

SRT='1\n00:00:14,000 --> 00:00:17,000\n跨段歌詞\n第二行\n\n2\n00:00:17.000 --> 00:00:30.000\n中段歌詞\n\n3\n00:00:30,000 --> 00:00:32,000\n尾段歌詞'


class LyricsReferenceTests(unittest.TestCase):
    def test_parse_bom_crlf_optional_numbers_and_multiline(self):
        cues=parse_srt('\ufeff'+SRT.replace('\n','\r\n'))
        self.assertEqual(cues[0],{'start':14,'end':17,'text':'跨段歌詞\n第二行'})
        self.assertEqual(parse_srt('00:00:00,000 --> 00:00:01,000\n一句')[0]['start'],0)
        self.assertEqual(parse_srt('  '),[])

    def test_half_open_boundaries_and_partial_last_segment(self):
        req=normalize_references({'srt_reference':SRT},31)
        self.assertEqual([c['text'] for c in excerpt(req,{'start':0,'seconds':15})],['跨段歌詞\n第二行'])
        middle=excerpt(req,{'start':15,'seconds':15})
        self.assertEqual(len(middle),2)
        self.assertEqual((middle[0]['clip_start'],middle[0]['clip_end']),(0,2))
        tail=excerpt(req,{'start':30,'seconds':1})
        self.assertEqual([c['text'] for c in tail],['尾段歌詞'])
        self.assertEqual(tail[0]['clip_end'],1)
        self.assertEqual(excerpt(req,{'start':3,'seconds':5}),[])

    def test_invalid_times_empty_text_limits_and_out_of_range(self):
        for raw in ('not srt','1\n00:99:00,000 --> 00:00:01,000\nx',
                    '00:00:02,000 --> 00:00:01,000\nx','00:00:00,000 --> 00:00:01,000',None,'x'*60001):
            with self.assertRaises(ValueError):parse_srt(raw)
        with self.assertRaisesRegex(ValueError,'範圍外'):
            normalize_references({'srt_reference':SRT},10)
        with self.assertRaises(ValueError):normalize_references({'lyrics':'x'*12001},60)

    def test_text_only_srt_only_and_untrusted_cue_objects(self):
        req=normalize_references({'lyrics':'全曲內容','srt_cues':[{'text':'偽造'}]},60)
        self.assertEqual(req['srt_cues'],[])
        self.assertIn('全曲內容',clip_reference(req,{'start':0,'seconds':15}))
        srt_only=normalize_references({'srt_reference':SRT},60)
        text=clip_reference(srt_only,{'start':0,'seconds':15})
        self.assertIn('跨段歌詞',text);self.assertNotIn('尾段歌詞',text)
        self.assertEqual(clip_reference({},{}),'')
        self.assertEqual(json.loads(json.dumps(srt_only,ensure_ascii=False)),srt_only)

    def test_planner_receives_aligned_excerpts_and_plain_song_context(self):
        from banana_mv.story_plan import plan_input
        req=normalize_references({'lyrics':'整首背景','srt_reference':SRT},31)
        text=plan_input(req,[{'index':0,'start':0,'seconds':15},{'index':1,'start':15,'seconds':15},{'index':2,'start':30,'seconds':1}])
        rows=json.loads(text.split('MEASURED TIMELINE (null means unmeasured, not silence):\n')[1])
        self.assertIn('整首背景',text)
        self.assertEqual(len(rows[1]['srt_excerpts']),2)
        self.assertEqual(rows[2]['srt_excerpts'][0]['text'],'尾段歌詞')

    def test_rewriter_gets_lyrics_as_context_not_final_prompt_or_subtitles(self):
        from PIL import Image
        from banana_mv import server
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);photo=root/'ref.png';Image.new('RGB',(16,16)).save(photo)
            guide=root/'guide.md';guide.write_text('H3 guide')
            req=normalize_references({'prompt':'舞台演唱','lyrics':'全曲背景歌詞','srt_reference':SRT,
                                      'optimizer_version':1,'rewrite':True},32)
            segment={'start':0,'seconds':15,'index':0,'model_frames':362}
            with patch.object(server.backend,'rewrite_local',return_value='summary: A singer performs with <Audio 1>. <d>[Chinese] 跨段歌詞</d>') as model:
                result=server.local_prompt({'guides':{'ref':str(guide)}},req,segment,[photo],None)
            model_text='\n'.join(value for kind,value in model.call_args.args[2] if kind=='text')
            self.assertIn('全曲背景歌詞',model_text);self.assertIn('跨段歌詞',model_text)
            self.assertNotIn('尾段歌詞',model_text)
            self.assertNotIn('全曲背景歌詞',result);self.assertNotIn('跨段歌詞',result)
            self.assertEqual(model.call_count,1)
            self.assertNotIn('<d>',result)
            self.assertIn('SOURCE AUDIO / VISIBLE ROLE SEPARATION',result)
            self.assertGreater(segment['lyric_reference_cleanup']['removed_spans'],0)
            self.assertIn('FINAL LYRIC OUTPUT OVERRIDE',model.call_args.args[1])
            req['rewrite']=False
            result=server.local_prompt({},req,segment,[photo],None)
            self.assertNotIn('全曲背景歌詞',result)

    def test_output_cleanup_removes_speech_tags_and_exact_quotes_without_a_semantic_judge(self):
        from banana_mv.lyrics_reference import clean_lyric_output
        req=normalize_references({'lyrics':'拳風擦過耳邊\n[Verse]','srt_reference':SRT},32)
        draft='[Shot 1] A fighter dodges, <d>[Chinese] 拳風擦過耳邊</d>.\nSoundtrack cue: 「跨段歌詞」.\n拳風擦過耳邊\n拳風擦過耳邊時，她側身閃避。'
        cleaned,count=clean_lyric_output(draft,req)
        self.assertNotIn('<d>',cleaned);self.assertNotIn('[Chinese]',cleaned)
        self.assertNotIn('「跨段歌詞」',cleaned)
        self.assertIn('拳風擦過耳邊時，她側身閃避。',cleaned) # retain visual-event descriptions
        self.assertGreaterEqual(count,3)
        self.assertEqual(clean_lyric_output(draft,{}),(draft,0))

    def test_finished_video_export_keeps_master_and_uses_safe_unique_names(self):
        from banana_mv import server
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);master=root/'final.mp4';master.write_bytes(b'finished-video')
            with patch.object(server.backend,'DATA',root):
                job={'id':'123456789abc','title':'作品/同名:測試'}
                output=server.export_finished_video(job,master)
                self.assertEqual(output.parent,root/'videos')
                self.assertNotIn('/',output.name);self.assertNotIn(':',output.name)
                self.assertEqual(master.read_bytes(),output.read_bytes())
                second=server.export_finished_video({'id':'abcdef123456','title':job['title']},master)
                self.assertNotEqual(output,second)
                with patch.object(server.shutil,'copyfile',side_effect=OSError('disk full')):
                    with self.assertRaises(OSError):server.export_finished_video(job,master)
                self.assertTrue(master.exists());self.assertTrue(output.exists())
                self.assertFalse(any(p.suffix=='.tmp' for p in (root/'videos').iterdir()))
