"""Opt-in temporal repair for the Windows 5070 MV workflow."""
CHECKPOINT = 'minimax_h3_latent_upscaler_3d_conv_v2_temporal_bf16.safetensors'
MOTION_MODE = 'auto_2x'
CAPABILITY_NODE = 'BananaH3TLUCapability'


def validate_request(request, *, local5070):
    if not local5070 or request.get('h3_nvfp4') or request.get('native_sound'):
        raise ValueError('高速動態修復目前只支援本機 5070 的 PRISM INT8 原音軌工作流。')


def _combo_options(info, name, field):
    """Read legacy list choices and current ComfyUI COMBO metadata."""
    fields = info.get(name, {}).get('input', {})
    accepted = fields.get('required', {}) | fields.get('optional', {})
    spec = accepted.get(field)
    if not isinstance(spec, (list, tuple)) or not spec:
        return []
    if isinstance(spec[0], list):
        return spec[0]
    if spec[0] == 'COMBO' and len(spec) > 1 and isinstance(spec[1], dict):
        options = spec[1].get('options')
        if isinstance(options, list):
            return options
    return []


def require_capability(info):
    expected = {
        'H3TemporalInsert': ((), ()),
        'H3AdaptiveLatentRepair': (
            ('samples', 'conditioning', 'checkpoint', 'motion_mode',
             'spatial_scale', 'untouched_spatial_denoise'), ('LATENT', 'CONDITIONING', 'STRING')),
        'H3RepairSchedule': (
            ('model', 'samples', 'scheduler', 'total_steps', 'inject', 'skip_if_unmasked'), ('SIGMAS',)),
        'H3ExactVAEDecode': (('samples', 'vae', 'hold_map', 'trim_tail_padding'), ('IMAGE',)),
        CAPABILITY_NODE: (('readiness',), ()),
    }
    missing = sorted(set(expected) - set(info))
    if missing:
        raise ValueError('高速動態修復缺少節點：' + '、'.join(missing) + '。請執行安裝包並重啟 ComfyUI。')
    for name, (inputs, outputs) in expected.items():
        node = info[name]
        fields = node.get('input', {})
        accepted = fields.get('required', {}) | fields.get('optional', {})
        if not set(inputs) <= set(accepted) or tuple(node.get('output', ())[:len(outputs)]) != outputs:
            raise ValueError(f'高速動態修復節點介面不相容：{name}。')
    status = _combo_options(info, CAPABILITY_NODE, 'readiness')
    if status != ['ready']:
        detail = status[0] if isinstance(status, list) and status else '未知狀態'
        raise ValueError('高速動態修復尚未就緒：' + str(detail))
    for name, field, value in (
        ('H3AdaptiveLatentRepair', 'checkpoint', CHECKPOINT),
        ('H3AdaptiveLatentRepair', 'motion_mode', MOTION_MODE),
        ('H3RepairSchedule', 'scheduler', 'beta'),
        ('KSamplerSelect', 'sampler_name', 'res_multistep'),
    ):
        options = _combo_options(info, name, field)
        if not isinstance(options, list) or value not in options:
            raise ValueError(f'高速動態修復不支援 {name}.{field} = {value}。')


def add_temporal_repair(graph, *, h3_nvfp4, native_sound):
    if h3_nvfp4 or native_sound:
        raise ValueError('高速動態修復目前只支援 PRISM INT8 的原音軌片段。')

    def node(kind, **inputs):
        return {'class_type': kind, 'inputs': inputs}

    # Pass 2 has its own sampling settings and a clean model branch.
    # Pass 1 keeps its selected LoRAs, attention settings and Euler schedule.
    shift = dict(graph['8']['inputs'], model=['1', 0])
    graph.update({
        'tlu_repair': node('H3AdaptiveLatentRepair',
                           samples=['13', 0], conditioning=graph['9']['inputs']['conditioning'],
                           checkpoint=CHECKPOINT, motion_mode=MOTION_MODE,
                           spatial_scale=1.0, untouched_spatial_denoise=1.0),
        'tlu_model': node(graph['8']['class_type'], **shift),
        'tlu_sigmas': node('H3RepairSchedule', model=['tlu_model', 0], samples=['tlu_repair', 0],
                           scheduler='beta', total_steps=12, inject=0.42, skip_if_unmasked=True),
        'tlu_guider': node('BasicGuider', model=['tlu_model', 0], conditioning=['tlu_repair', 1]),
        'tlu_sampler': node('KSamplerSelect', sampler_name='res_multistep'),
        'tlu_sample': node('SamplerCustomAdvanced', noise=['10', 0], guider=['tlu_guider', 0],
                           sampler=['tlu_sampler', 0], sigmas=['tlu_sigmas', 0],
                           latent_image=['tlu_repair', 0]),
        '14': node('H3ExactVAEDecode', samples=['tlu_sample', 0], vae=['3', 0],
                   hold_map=['tlu_repair', 2], trim_tail_padding=True),
    })
