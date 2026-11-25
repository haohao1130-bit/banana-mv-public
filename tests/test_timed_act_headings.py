import unittest

class TimedActWithoutSpaceTests(unittest.TestCase):
    """32b314ea7d8d：「ACT01｜00:00–00:10」沒空格、最後一章寫「音源結束」。"""

    def test_timed_acts_follow_song_time_and_audio_end(self):
        from banana_mv import python_slots
        from banana_mv.timed_slots import allocate_timed_chapters, parse_timed_source
        acts = '\n'.join(
            f'ACT{n:02d}｜{(n-1)*10//60:02d}:{(n-1)*10%60:02d}–{n*10//60:02d}:{n*10%60:02d}\nS1 做第 {n} 段的動作。'
            + ('\nS1 這段動作很多。' * 8 if n == 2 else '')
            for n in range(1, 4))
        text = acts + '\nACT04｜00:30–音源結束\nS1 收尾。\nHARD END.'
        fixed, chapters = parse_timed_source(text)
        self.assertEqual([c['title'][:5] for c in chapters], ['ACT01', 'ACT02', 'ACT03', 'ACT04'])
        song = [{'index': i, 'start': i * 10.0, 'seconds': 10.0} for i in range(4)]
        song.append({'index': 4, 'start': 40.0, 'seconds': 9.6})
        allocated = allocate_timed_chapters(chapters, song, python_slots.commission)
        import re
        scenes = [re.search(r'(?:Source chapter: |scene )(ACT\d+)', event)[1] for event in allocated]
        # 動作最多的 ACT02 不會多拿一段；多出來的那段給「到音源結束」的 ACT04。
        self.assertEqual(scenes, ['ACT01', 'ACT02', 'ACT03', 'ACT04', 'ACT04'])
        self.assertIn('30.000–49.600s', allocated[4])
        self.assertIn('HARD END', allocated[4])


if __name__ == '__main__':
    unittest.main()
