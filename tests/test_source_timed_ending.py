"""VNext source-time ending semantics adapted to Classic (offline, no GPU)."""
import unittest
from banana_mv.mv_scope import ending_contract, clip_ending
from banana_mv.core import segments


class SourceTimedEndingTests(unittest.TestCase):
    def req(self, **extra):
        return {'project_scope': 'full', 'ending_policy_version': 2, **extra}

    def test_full_song_has_no_forced_final_hold(self):
        song=segments(60, 10)
        contract=ending_contract(self.req(),60,song)
        self.assertEqual(contract['finale_policy'],'source_duration_v2')
        self.assertEqual(contract['settle_by'],60)
        self.assertEqual(contract['hold_seconds'],0)
        self.assertEqual(contract['short_tail_seconds'],0)
        penultimate=clip_ending(self.req(), dict(song[-2],song_seconds=60,segment_count=len(song),
                                                  direction_ending_contract=contract))
        last=clip_ending(self.req(), dict(song[-1],song_seconds=60,segment_count=len(song),
                                           direction_ending_contract=contract))
        self.assertEqual(penultimate['phase'],'continuing')
        self.assertFalse(penultimate['finish_work'])
        self.assertEqual(last['phase'],'resolving')
        self.assertNotIn('hold',last['instruction'].lower())

    def test_short_residual_finishes_in_preceding_full_clip(self):
        for seconds, tail in ((202,2),(203,3),(72,2)):
            song=segments(seconds,10)
            contract=ending_contract(self.req(),seconds,song)
            self.assertEqual(contract['short_tail_seconds'],tail)
            self.assertEqual(contract['settle_by'],seconds-tail)
            previous=clip_ending(self.req(),dict(song[-2],song_seconds=seconds,segment_count=len(song),
                                                 direction_ending_contract=contract))
            final=clip_ending(self.req(),dict(song[-1],song_seconds=seconds,segment_count=len(song),
                                              direction_ending_contract=contract))
            self.assertEqual(previous['phase'],'resolving')
            self.assertEqual(final['phase'],'terminal_hold')
            self.assertIn('Do not replay',final['instruction'])

    def test_non_tiny_tail_can_resolve_on_the_actual_song_end(self):
        song=segments(204,10)
        contract=ending_contract(self.req(),204,song)
        self.assertEqual(contract['short_tail_seconds'],0)
        self.assertEqual(contract['settle_by'],204)
        final=clip_ending(self.req(),dict(song[-1],song_seconds=204,segment_count=len(song),
                                          direction_ending_contract=contract))
        self.assertEqual(final['phase'],'resolving')

    def test_user_hold_is_opt_in_and_excerpt_has_no_finale(self):
        song=segments(60,10)
        contract=ending_contract(self.req(final_hold_seconds=2),60,song)
        self.assertEqual(contract['settle_by'],58)
        self.assertEqual(contract['hold_seconds'],2)
        excerpt={'project_scope':'excerpt','ending_policy_version':2}
        contract=ending_contract(excerpt,60,song)
        self.assertFalse(contract['finish_work'])
        final=clip_ending(excerpt,dict(song[-1],song_seconds=60,segment_count=len(song),
                                       direction_ending_contract=contract))
        self.assertFalse(final['finish_work'])

    def test_existing_jobs_still_use_legacy_contract(self):
        song=segments(60,10)
        old=ending_contract({'project_scope':'full'},60,song)
        self.assertEqual(old['settle_by'],58.5)
        self.assertNotIn('finale_policy',old)

    def test_invalid_explicit_hold_is_rejected(self):
        for bad in (True,-1,60,float('nan'),float('inf')):
            with self.subTest(value=bad),self.assertRaises(ValueError):
                ending_contract(self.req(final_hold_seconds=bad),60,segments(60,10))


if __name__=='__main__':
    unittest.main()
