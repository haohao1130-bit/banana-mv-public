"""Text-only segment placement; not beat analysis or an automatic storyboard planner."""


def segment_context(segment):
    total = segment.get('song_seconds')
    count = segment.get('segment_count', 1)
    if not total or count <= 1:
        return ''
    index = segment['index']
    last = index == count-1
    progress = segment['start']/total
    phase = 'closing' if last else 'opening' if index == 0 else 'late development' if progress >= .7 else 'development'
    ending = ('The song reaches its ending in this window; complete the requested final resolution here.' if last else
              'This is NOT the song ending. Do not finish the whole story, defeat all opponents, take a final bow or end the show here.')
    return (f'SONG TIMELINE: segment {index+1}/{count}, source interval '
            f'{segment["start"]:.3f}–{min(total, segment["start"]+segment["seconds"]):.3f}s '
            f'of {total:.3f}s. Narrative phase: {phase}. '
            'The user description is the whole-song brief. Choose only events appropriate to this interval, '
            'not the entire plot in every clip. Preserve identity, costumes and recurring locations. '
            'For independent segments, do not require matching the previous final camera composition. '
            'For continuation segments, respect the supplied first frame. '
            'Any shot timestamps in this output must be local to this clip, not absolute song timestamps. ' + ending)
