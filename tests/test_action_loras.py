import io
import unittest
from contextlib import redirect_stdout

from banana_mv.core import (action_lora_brief, build_workflow, inject_action_triggers,
                            normalize_action_loras)

PROMPT = ('subject_definitions:\n<Subject 1> is from <Picture 2>.\n\nsummary:\nA fight.\n\n'
          'detailed_description:\nUse the original song from <Audio 1> unchanged (fully_copy).\n'
          '[Shot 1] He blocks.\n\noverall_soundscape:\nsong')
ARGS = ('ref.png', 'slice.wav', 1024, 576, 241, PROMPT, 42, 'tail.png')
ALL_ON = {'combat': {'enabled': True, 'strength': 0.5, 'trigger': 'prfight2'},
          'fight_flow': {'enabled': True, 'strength': 0.65, 'mode': 'unarmed'},
          'repair': {'enabled': True, 'strength': 0.5, 'version': 'v2', 'trigger': True}}
ALL_OFF = {'combat': {'enabled': False}, 'fight_flow': {'enabled': False}, 'repair': {'enabled': False}}


def build(**kw):
    with redirect_stdout(io.StringIO()) as out:
        graph = build_workflow(*ARGS, **kw)
    return graph, out.getvalue()


class ActionLoraPanel(unittest.TestCase):
    def test_all_on_mounts_three_in_fixed_order_with_exact_strengths(self):
        graph, log = build(action_loras=ALL_ON, director_mode='performance', intensity='extreme')
        self.assertEqual(graph['action_combat']['inputs']['model'], ['1', 0])
        self.assertEqual(graph['action_fight_flow']['inputs']['model'], ['action_combat', 0])
        self.assertEqual(graph['action_repair']['inputs']['model'], ['action_fight_flow', 0])
        self.assertEqual([graph[k]['inputs']['lora_name'] for k in ('action_combat', 'action_fight_flow', 'action_repair')],
                         ['H3_Combat_V2.safetensors', 'H3_Fight_Flow_V2.safetensors', 'Motion_Repair_V2.safetensors'])
        # 權重就是實際值：電影級爆發也不再乘 1.3。
        self.assertEqual([graph[k]['inputs']['strength_model'] for k in ('action_combat', 'action_fight_flow', 'action_repair')],
                         [0.5, 0.65, 0.5])
        self.assertNotIn('motion_combat', graph)
        self.assertNotIn('motion_repair', graph)
        self.assertIn('mounted=3', log)

    def test_triggers_lead_detailed_description_once(self):
        graph, _ = build(action_loras=ALL_ON)
        text = graph['7']['inputs']['prompt']
        self.assertIn('detailed_description:\nprfight2. Unarmed combat interaction. bunny_crisp_motion\n'
                      'Use the original song', text)
        self.assertTrue(text.startswith('subject_definitions:'))
        self.assertEqual(text.count('Unarmed combat interaction.'), 1)
        # 9B 已經寫了同一句，就不再重複。
        again = inject_action_triggers(text, ['Unarmed combat interaction.'])
        self.assertEqual(again, text)

    def test_all_off_is_identical_to_no_loras(self):
        base, _ = build(motion_lora=False)
        off, log = build(action_loras=ALL_OFF, motion_lora=True)
        self.assertEqual(base, off)
        self.assertIn('mounted=0 triggers=(none)', log)

    def test_strength_zero_means_not_loaded_and_no_trigger(self):
        loras = dict(ALL_OFF, fight_flow={'enabled': True, 'strength': 0, 'mode': 'melee'})
        graph, _ = build(action_loras=loras)
        self.assertNotIn('action_fight_flow', graph)
        self.assertNotIn('Melee weapon interaction.', graph['7']['inputs']['prompt'])

    def test_combat_without_trigger_still_loads_and_repair_v1_kept(self):
        loras = {'combat': {'enabled': True, 'strength': 0.65, 'trigger': 'none'},
                 'fight_flow': {'enabled': False},
                 'repair': {'enabled': True, 'strength': 0.35, 'version': 'v1', 'trigger': False}}
        graph, _ = build(action_loras=loras)
        self.assertEqual(graph['action_combat']['inputs']['lora_name'], 'H3_Combat_V2.safetensors')
        self.assertEqual(graph['action_repair']['inputs']['lora_name'], 'Motion_Repair.safetensors')
        self.assertEqual(graph['7']['inputs']['prompt'], PROMPT)

    def test_old_projects_keep_old_motion_lora_graph(self):
        legacy, _ = build(director_mode='action', intensity='high')
        self.assertEqual(legacy['motion_combat']['inputs']['strength_model'], 0.65)
        self.assertEqual(legacy['motion_repair']['inputs']['lora_name'], 'Motion_Repair.safetensors')
        self.assertNotIn('action_combat', legacy)
        self.assertEqual(legacy['7']['inputs']['prompt'], PROMPT)

    def test_plain_prompt_gets_trigger_on_top(self):
        self.assertEqual(inject_action_triggers('A duel.', ['Gun-fu interaction.']), 'Gun-fu interaction.\nA duel.')

    def test_bad_settings_are_rejected(self):
        for bad in ({'combat': {'enabled': True, 'strength': 2}},
                    {'fight_flow': {'enabled': True, 'mode': 'kungfu'}},
                    {'repair': {'version': 'v3'}},
                    {'combat': {'enabled': 'yes'}},
                    {'laser': {}}):
            with self.assertRaises(ValueError):
                normalize_action_loras(bad)

    def test_9b_brief_only_when_something_is_on(self):
        self.assertEqual(action_lora_brief({}), '')
        self.assertEqual(action_lora_brief({'action_loras': ALL_OFF}), '')
        brief = action_lora_brief({'action_loras': ALL_ON})
        self.assertIn('do not write them', brief)
        self.assertIn('unarmed combat interaction', brief)
        self.assertNotIn('prfight2', brief)



class DanceLoraTests(unittest.TestCase):
    def test_dance_mounts_and_weights(self):
        base, _ = build(action_loras={})
        off, _ = build(action_loras={'dance': {'enabled': False}, 'beat_sync': {'enabled': True, 'strength': 0}})
        self.assertEqual(base, off)
        graph, _ = build(action_loras={'dance': {'enabled': True}, 'beat_sync': {'enabled': True, 'strength': 1.35},
                                      'choreography': {'enabled': True}, 'repair': {'enabled': True}})
        self.assertEqual(graph['action_dance']['inputs']['strength_model'], 0.7)
        self.assertEqual(graph['action_beat_sync']['inputs']['strength_model'], 1.35)
        self.assertEqual(graph['action_choreography']['inputs']['strength_model'], 0.4)
        self.assertEqual(graph['action_repair']['inputs']['model'], ['action_choreography', 0])
        self.assertEqual(action_lora_brief({'action_loras': {'dance': {'enabled': True}}}), '')
        with self.assertRaises(ValueError):
            normalize_action_loras({'beat_sync': {'strength': 2.01}})
        with self.assertRaises(ValueError):
            normalize_action_loras({'dance': {'strength': 1.01}})


if __name__ == '__main__':
    unittest.main()


class ActionLoraServerOptions(unittest.TestCase):
    def test_graph_options_forward_panel_only_when_present(self):
        from banana_mv.server import graph_options
        options = graph_options({'director': 'performance', 'action_loras': ALL_ON}, 10)
        self.assertEqual(options['action_loras']['repair']['version'], 'v2')
        self.assertNotIn('action_loras', graph_options({'director': 'performance'}, 10))
        with self.assertRaises(ValueError):
            graph_options({'director': 'performance', 'action_loras': {'combat': {'strength': -1}}}, 10)
