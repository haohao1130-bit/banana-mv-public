from copy import deepcopy
import unittest
from unittest.mock import patch

from banana_mv import anti_jelly, server
from banana_mv.core import align_frames, build_workflow


def node_info():
    def node(fields, output=(), **options):
        return {'input': {'required': {key: options.get(key, ['ANY']) for key in fields}},
                'output': list(output)}

    return {
        'H3TemporalInsert': node(()),
        'H3AdaptiveLatentRepair': node(
            ('samples', 'conditioning', 'checkpoint', 'motion_mode',
             'spatial_scale', 'untouched_spatial_denoise'),
            ('LATENT', 'CONDITIONING', 'STRING', 'INT', 'STRING'),
            checkpoint=[[anti_jelly.CHECKPOINT]], motion_mode=[[anti_jelly.MOTION_MODE]],
        ),
        'H3RepairSchedule': node(('model', 'samples', 'scheduler', 'total_steps', 'inject', 'skip_if_unmasked'),
                                 ('SIGMAS',), scheduler=[['beta']]),
        'H3ExactVAEDecode': node(('samples', 'vae', 'hold_map', 'trim_tail_padding'), ('IMAGE',)),
        anti_jelly.CAPABILITY_NODE: node(('readiness',), readiness=[['ready']]),
        'KSamplerSelect': node(('sampler_name',), sampler_name=[['euler', 'res_multistep']]),
    }


class TemporalRepairTests(unittest.TestCase):
    def test_default_graph_and_repair_graph_for_every_generation_mode(self):
        for seconds in (10, 15):
            cases = {
                'independent': (None, None),
                'chain': ('first.png', None),
                'chain5': ('first.png', ['first.png', '2.png', '3.png', '4.png', '5.png']),
            }
            for mode, (first, guides) in cases.items():
                with self.subTest(seconds=seconds, mode=mode), patch.object(server.backend, 'PORT', 8193):
                    request = dict(mode=mode, width=854, sampling_steps=12,
                                   action_loras={'combat': {'enabled': True, 'strength': 0.5}})
                    def build(req):
                        return build_workflow('ref.png', 'source.wav', 864, 480,
                                              align_frames(seconds * 24), 'A shot', 70, first,
                                              guide_frames=guides, **server.graph_options(req, seconds))
                    baseline = build(request)
                    self.assertEqual(baseline, build(dict(request, anti_jelly=False)))
                    repaired = build(dict(request, anti_jelly=True))
                    self.assertEqual(repaired['12']['inputs']['steps'], 12)
                    self.assertEqual(repaired['tlu_repair']['inputs']['conditioning'],
                                     baseline['9']['inputs']['conditioning'])
                    self.assertEqual(repaired['tlu_model']['inputs']['model'], ['1', 0])
                    self.assertEqual(repaired['14']['inputs']['hold_map'], ['tlu_repair', 2])
                    self.assertEqual(repaired['15']['inputs']['audio'], ['7', 2])
                    self.assertEqual(repaired['tlu_sigmas']['inputs']['inject'], 0.42)
                    for key, value in baseline.items():
                        if key != '14':
                            self.assertEqual(repaired[key], value)

    def test_preflight_requires_real_checkpoint_and_pinned_interface(self):
        info = node_info()
        anti_jelly.require_capability(info)
        missing = deepcopy(info)
        missing.pop('H3TemporalInsert')
        with self.assertRaisesRegex(ValueError, 'H3TemporalInsert'):
            anti_jelly.require_capability(missing)
        incompatible = deepcopy(info)
        incompatible['H3ExactVAEDecode']['input']['required'].pop('hold_map')
        with self.assertRaisesRegex(ValueError, 'H3ExactVAEDecode'):
            anti_jelly.require_capability(incompatible)
        info[anti_jelly.CAPABILITY_NODE]['input']['required']['readiness'] = [['FileNotFoundError']]
        with self.assertRaisesRegex(ValueError, 'FileNotFoundError'):
            anti_jelly.require_capability(info)

    def test_preflight_accepts_current_combo_metadata_and_mixed_formats(self):
        info = node_info()
        fields = (
            ('H3AdaptiveLatentRepair', 'checkpoint'),
            ('H3AdaptiveLatentRepair', 'motion_mode'),
            ('H3RepairSchedule', 'scheduler'),
            ('KSamplerSelect', 'sampler_name'),
            (anti_jelly.CAPABILITY_NODE, 'readiness'),
        )
        for name, field in fields:
            required = info[name]['input']['required']
            options = required[field][0]
            required[field] = ['COMBO', {'default': options[0], 'options': options,
                                         'multiselect': False}]
            anti_jelly.require_capability(info)

    def test_preflight_rejects_missing_or_invalid_combo_choices(self):
        for spec in (
            ['COMBO', {'default': anti_jelly.CHECKPOINT, 'options': ['other.safetensors']}],
            ['COMBO', {'default': anti_jelly.CHECKPOINT}],
            ['COMBO', {'options': anti_jelly.CHECKPOINT}],
            ['COMBO', {}],
            [],
        ):
            with self.subTest(spec=spec):
                info = node_info()
                info['H3AdaptiveLatentRepair']['input']['required']['checkpoint'] = spec
                with self.assertRaisesRegex(ValueError, 'H3AdaptiveLatentRepair.checkpoint'):
                    anti_jelly.require_capability(info)
        info = node_info()
        info[anti_jelly.CAPABILITY_NODE]['input']['required']['readiness'] = [
            'COMBO', {'options': ['FileNotFoundError'], 'default': 'ready'}]
        with self.assertRaisesRegex(ValueError, 'FileNotFoundError'):
            anti_jelly.require_capability(info)

    def test_pass2_sparse_is_independent_and_opt_in(self):
        for seconds in (10, 15):
            for first_pass_sparse in (False, True):
                with self.subTest(seconds=seconds, first_pass_sparse=first_pass_sparse), patch.object(server.backend, 'PORT', 8193):
                    request = dict(sampling_steps=12, sparse_attention=first_pass_sparse,
                                   action_loras={'combat': {'enabled': True, 'strength': 0.5}})
                    def build(**options):
                        return build_workflow('ref.png', 'source.wav', 864, 480,
                                              align_frames(seconds * 24), 'A shot', 70,
                                              **server.graph_options(dict(request, **options), seconds))
                    baseline = build()
                    self.assertEqual(baseline, build(anti_jelly_sparse=True))
                    dense = build(anti_jelly=True)
                    self.assertEqual(dense, build(anti_jelly=True, anti_jelly_sparse=False))
                    sparse = build(anti_jelly=True, anti_jelly_sparse=True)
                    self.assertEqual(set(sparse) - set(dense), {'tlu_sparse'})
                    self.assertEqual(sparse['tlu_sparse']['class_type'], 'BlockSparseAttention')
                    opts = sparse['tlu_sparse']['inputs']
                    self.assertEqual(opts['model'], ['tlu_model', 0])
                    self.assertEqual(opts['selection'], 'sol-attn')
                    self.assertEqual(opts['selection.tau'], 1.3)
                    self.assertEqual(opts['min_tokens'], 20480)
                    self.assertEqual(opts['end_percent'], 0.95)
                    self.assertEqual(sparse['tlu_model']['inputs']['model'], ['1', 0])
                    for key in ('tlu_sigmas', 'tlu_guider'):
                        self.assertEqual(sparse[key]['inputs']['model'], ['tlu_sparse', 0])
                        self.assertEqual(dense[key]['inputs']['model'], ['tlu_model', 0])
                        self.assertEqual(dict(sparse[key]['inputs'], model=['tlu_model', 0]), dense[key]['inputs'])
                    for key in dense.keys() - {'tlu_sigmas', 'tlu_guider'}:
                        self.assertEqual(dense[key], sparse[key])
                    self.assertEqual('sparse_attention' in sparse, first_pass_sparse)
        with self.assertRaisesRegex(ValueError, 'anti_jelly_sparse'):
            server.graph_options({'anti_jelly_sparse': 'true'}, 10)

    def test_only_requested_feature_is_guarded(self):
        with patch.object(server.backend, 'PORT', 8190):
            self.assertNotIn('anti_jelly', server.graph_options({}, 15))
            with self.assertRaisesRegex(ValueError, '5070'):
                server.graph_options({'anti_jelly': True}, 15)
        with patch.object(server.backend, 'PORT', 8193):
            with self.assertRaisesRegex(ValueError, 'PRISM'):
                server.graph_options({'anti_jelly': True, 'h3_nvfp4': True}, 15)
            with self.assertRaisesRegex(ValueError, '布林'):
                server.graph_options({'anti_jelly': 'false'}, 15)
