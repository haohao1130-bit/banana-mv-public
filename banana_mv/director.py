"""Concrete visual direction; legacy projects retain their original rules."""
import re
MODES={
'performance':'Visible lip-synced lead singing, expressive stage action, audience and lighting reactions.',
'dance':'Evolving dance choreography, footwork, formation and movement continuity across cuts.',
'action':'Causal martial arts: anticipation, attack, defense, reaction, aftermath; consistent geography.',
'band':'Plausible instrument performance; alternate singer and musicians only when present.',
'chase':'Pursuit with obstacles, momentum, consistent direction and location.',
'fantasy':'Magic and transformation with setup, execution and visible consequence.',
'story':'Narrative cause and effect, emotional progression and meaningful reactions.',
'horror':'Suspense, subtle anomalies, reveal and reaction; restrained editing.',
'comedy':'Deadpan setup, complication, reaction and visual payoff.'
}
KEYWORDS=[('action','武打 打鬥 切磋 戰鬥 fight battle'),('dance','跳舞 舞蹈 熱舞 dance'),('band','樂團 吉他 鼓手 貝斯 band guitar'),('chase','追逐 跑酷 飛車 chase parkour'),('fantasy','魔法 法術 變身 召喚 magic'),('horror','恐怖 驚悚 懸疑 horror'),('comedy','搞笑 惡搞 爆笑 comedy'),('story','劇情 回憶 愛情 失戀 story romance')]
INTENSITY={'normal':'Natural grounded action.','high':'Energetic but readable action and camera movement.','extreme':'Cinematic peaks, preserve readable motion and identity.'}
def _legacy_director_prompt(req, seconds):
    mode=req.get('director','auto')
    if mode=='auto':
        content=(req.get('prompt','')+' '+req.get('lyrics','')).lower()
        mode=next((key for key,words in KEYWORDS if any(w in content for w in words.split())), 'performance')
    if mode not in MODES: raise ValueError('未知導演模式')
    strength=req.get('intensity','high')
    if strength not in INTENSITY: raise ValueError('未知動作強度')
    lines=['DIRECTOR GUIDANCE:',mode+': '+MODES[mode],INTENSITY[strength],
           'Event first, then character action, attention, camera and editing.',
           'Preserve performer identity, costumes, geography and source-audio lip synchronization. Do not invent lyrics.']
    if req.get('dynamic_cuts',True):
        lines.append('Use motivated editorial cuts and distinct camera compositions around 3–5 seconds where possible; short transition shots may appear anywhere. Cuts are flexible, not fixed to segment boundaries.')
    else: lines.append('Prefer motivated longer continuous takes.')
    return '\n'.join(lines),mode


RECIPES = {
    'performance': ('Give the singer a purposeful response to the current event: approach someone or something, '
                    'address it with gaze and a natural hand/torso action, then show its reaction. '
                    'Vary the performance action instead of repeating an idle pose; let hands participate when appropriate. '
                    'Use environment or supporting-character shots between singing shots when the brief supplies them.'),
    'dance': ('Develop one movement phrase: initiate a weight shift, carry momentum through a readable movement, '
              'then land or redirect it. Preserve limb continuity and movement direction across edits. '
              'Only use partners or formations already supplied; vary the phrase rather than restarting the same dance.'),
    'action': ('Show a complete causal exchange: threat approaches, the lead evades or blocks, '
               'then a short decisive counter produces a visible reaction and change of advantage. '
               'Keep attacker and defender spatially connected. A brief slow-motion evasion may reveal a near miss '
               'and the lead noticing an opening; resume normal speed for counter/contact/recoil. '
               'After a genuine reversal, allow a short low-angle hero view. Do not cut away before the consequence.'),
    'band': ('Connect a musician action to the performance: visible preparation, plausible playing gesture, '
             'then another supplied performer or the environment reacts. Alternate lead and existing musicians; '
             'keep instrument roles and hand contact plausible. Change the interaction instead of repeating instrument closeups.'),
    'chase': ('Establish pursuer, target and direction; use an obstacle already compatible with the location, '
              'show a readable choice to negotiate it, then reveal how distance or advantage changes. '
              'Keep screen direction and geography across cuts; preserve the chase rather than resetting positions.'),
    'fantasy': ('Prepare one transformation or magical action allowed by the brief, show its execution, '
                'then a persistent visible change and a character reaction. Effects originate from a clear action; '
                'do not replace story progression with unrelated particles or invent powers outside the brief.'),
    'story': ('Advance one assigned event through a concrete choice, an observable consequence and a response. '
              'Carry changed object/relationship/location state forward. Show what changes instead of generic looking '
              'or walking shots; reserve later events and the requested ending for their allocated segments.'),
    'horror': ('Build attention around a specific anomaly supplied by the story, hold long enough to notice it, '
               'reveal a little more, then show a restrained reaction. Use offscreen space and controlled silence; '
               'intensity means a stronger reveal, not automatic fast cuts or unrelated violence.'),
    'comedy': ('Present a legible deadpan setup, let one action cause an unexpected complication, '
               'then hold for the reaction or visual payoff. Preserve the prop and spatial relationship through the gag. '
               'Give the viewer time to understand it; avoid a new unrelated joke on every cut.'),
}

V2_KEYWORDS = [
    ('action', '武打 打鬥 切磋 戰鬥 拳擊 拳腳 格鬥 fight battle combat boxing martial'),
    ('dance', '跳舞 舞蹈 熱舞 dance dancing choreography'),
    ('band', '樂團 吉他 鼓手 貝斯 band guitar drummer bassist'),
    ('chase', '追逐 跑酷 飛車 chase chasing pursuit parkour'),
    ('fantasy', '魔法 法術 變身 召喚 magic transformation spell'),
    ('horror', '恐怖 驚悚 懸疑 horror suspense scary'),
    ('comedy', '搞笑 惡搞 爆笑 comedy funny deadpan joke'),
    ('story', '劇情 回憶 愛情 失戀 story narrative romance'),
]


def _mentions(text):
    """Conservative clause-level exclusions; handles common CN/EN negative scopes."""
    positive, excluded = set(), set()
    text = re.sub(r'\b(?:instead of|rather than)\b', 'without', text.lower())
    for clause in re.split(r'[，,。；;！!？?\n]|\b(?:but|instead)\b|但是|但|而是', text):
        clause = re.sub(r'不要只|不只|not only', '', clause)
        for mode, words in V2_KEYWORDS + [('performance', '演唱 唱歌 singing performance')]:
            for word in words.split():
                pattern = r'\b' + re.escape(word) + r'(?:s|ing)?\b' if word.isascii() else re.escape(word)
                for match in re.finditer(pattern, clause):
                    prefix = clause[:match.start()]
                    negative = re.search(r'不要|禁止|不准|避免|無需|不含|沒有|不加入|不需要|勿|不做|無|\b(?:no|not|never|without|avoid|exclude)\b|don.t', prefix)
                    suffix = clause[match.end():match.end()+5]
                    (excluded if negative or re.match(r'\s*(?:不要|禁止)', suffix) else positive).add(mode)
    return positive-excluded, excluded


def mode_candidates(req):
    positive, excluded = _mentions(req.get('prompt', ''))
    if req.get('optimizer_version', 0) >= 1:
        # Local role/scene prohibitions must not disable that mode everywhere.
        positive, excluded = set(), set()
        for clause in re.split(r'[，,。；;！!？?\n]', req.get('prompt','')):
            yes, no = _mentions(clause)
            scoped = re.search(r'(?:場|台|畫面|鏡頭|人物|角色|對手|其他|\bin\b|\bat\b|scene|stage|arena|opponent|others).*(?:不|禁止|\bno\b|\bnot\b|never)',clause,re.I)
            scoped = scoped or re.search(r'不讓.+(?:場|台|人物|角色)',clause)
            positive |= yes
            if not scoped:
                excluded |= no
    if not positive:
        lyric_modes, _ = _mentions(req.get('lyrics', ''))
        positive |= lyric_modes-excluded
    # Singing is the default MV grammar, unless the user explicitly excludes it.
    allowed = positive | ({'performance'} if 'performance' not in excluded else set())
    return allowed-excluded, excluded


def resolve_modes(req, segment=None):
    requested = req.get('director', 'auto')
    if requested != 'auto' and requested not in MODES:
        raise ValueError('未知導演模式')
    allowed, excluded = mode_candidates(req)
    if req.get('director_authority') and req.get('story_plan',True) and req.get('rewrite',True):
        chosen=(segment or {}).get('director_plan',{}).get('mode')
        if chosen in MODES and chosen not in excluded:
            return [chosen]
    if req.get('optimizer_version', 0) >= 1:
        event = (segment or {}).get('director_plan', {}).get('event','')
        planned = (segment or {}).get('director_plan', {}).get('mode')
        # Explicit action strengthens fights; it does not turn stage events into fights.
        if planned in ('performance','band') and planned in allowed:
            return [planned]
        if event:
            local, _ = _mentions(event)
            local &= allowed
            if local & {'performance','band'} and 'action' not in local:
                return ['band' if 'band' in local and 'performance' not in local else 'performance']
    if requested != 'auto' and requested not in excluded:
        return [requested]
    planned = (segment or {}).get('director_plan', {}).get('mode')
    if planned in allowed:
        primary = planned
    else:
        primary = next((key for key,_ in V2_KEYWORDS if key in allowed), 'performance')
    # No narrative genre inference solely from loudness; exclusions always win.
    if primary in excluded:
        return []
    other = next((key for key,_ in V2_KEYWORDS if key in allowed and key != primary), None)
    return [primary] + ([other] if other else [])


def performance_scene_modes(req):
    """Only activities positively present in the brief, not the MV default."""
    explicit = set()
    for clause in re.split(r'[，,。；;！!？?\n]',req.get('prompt','')):
        explicit |= _mentions(clause)[0]
    return explicit & mode_candidates(req)[0] & {'performance','band'}


def director_prompt(req, seconds, segment=None):
    if req.get('director_version', 1) < 2:
        return _legacy_director_prompt(req, seconds)
    strength = req.get('intensity', 'high')
    if strength not in INTENSITY:
        raise ValueError('未知動作強度')
    modes = resolve_modes(req, segment)
    primary = modes[0] if modes else 'performance'
    lines = ['DIRECTOR GUIDANCE V2: User events, exclusions and singer roles take priority.',
             'Event -> character action -> attention -> camera -> edit. Show a visible consequence before moving on.',
             'When a singer is visible, use waist-up or closer for clear identity and source-audio lip sync. '
             'Balance singing with separate story/environment shots; do not impose a fixed singer quota. '
             'Preserve costumes, locations and source audio; do not invent lyrics.']
    if req.get('director_authority') and req.get('story_plan',True) and req.get('rewrite',True):
        lines[0]='DIRECTOR GUIDANCE: The director treatment controls pacing and editing; preserve reference identities, voice roles and explicit non-negotiable restrictions.'
    if req.get('optimizer_version',0) >= 1:
        lines[1] = ('MUSIC-VIDEO ROUTING: source music and supplied music evidence -> clip function -> '
                    'user scene/event -> character action and attention -> camera and music-motivated editing. '
                    'Do not treat the MV as a continuous genre short film or force setup into every clip.')
    lines += [mode + ': ' + RECIPES[mode] for mode in modes]
    if req.get('optimizer_version', 0) >= 1:
        lines.append('SCENE ROUTING: Apply each recipe only to the shots where that activity actually occurs. '
                     'A selected action style must not add combat to a performance scene. Preserve the user-defined '
                     'scene boundaries, props, vocal roles and first-frame event; switch scenes by editing, not by merging sets. '
                     'MOVEMENT: Give each turn a target or interaction; feet, hips, shoulders and gaze turn coherently. '
                     'Use one primary camera move per shot. Avoid stacking a spin, orbit, rush-in and hair toss into one short beat.')
    if len(modes) > 1:
        lines.append('Use the primary recipe for this assigned event; the secondary recipe is optional, '
                     'only if the event and available time support it. Do not cram every genre into the clip.')
    if seconds <= 5:
        lines.append('Short window: show one legible action and its reaction, or complete one ongoing beat. '
                     'Do not squeeze a full multi-stage sequence into this clip.')
    if strength == 'normal':
        lines.append('NATURAL: one grounded action, restrained camera travel, clear preparation and reaction; let the event breathe.')
    elif strength == 'high':
        lines.append('HIGH: give the assigned event a clear change of momentum through purposeful body motion '
                     'and a motivated camera move. Keep the action readable and show the consequence.')
    else:
        evidence = (segment or {}).get('audio_evidence', {})
        quiet = evidence.get('relative_energy') in ('low', 'quiet') and evidence.get('energy_change_db', 0) < 3
        accents = evidence.get('transient_candidates_s', [])
        if quiet:
            lines.append('CINEMATIC CONTRAST: this measured interval is quieter. Hold tension, attention and controlled movement; '
                         'reserve the large payoff for a later supported rise. Do not force an explosion into every segment.')
        else:
            lines.append('CINEMATIC PEAK: prepare one event-specific turning point, deliver a decisive action/reveal, '
                         'then hold the reaction or aftermath. Use scale, speed contrast or a camera reveal to amplify the '
                         'consequence; do not equate intensity with constant speed, random destruction or added effects.')
            if accents:
                peak = min(accents, key=lambda t: abs(t-seconds*.65))
                lines.append(f'Candidate payoff near local {peak:.2f}s (estimated acoustic accent); '
                             'choose it only if the assigned action can land naturally, and allow reaction time.')
    if req.get('dynamic_cuts', True):
        if req.get('optimizer_version',0)>=1:
            lines.append('MUSIC-LED EDITING: choose shot length from musical phrasing, vocal delivery, measured accents '
                         'and the current action. Mix held shots with shorter inserts when useful; no fixed cut interval. '
                         'An accent can land through a gesture, impact, light change or reveal without a cut. '
                         'Return to supplied performance setups or visual motifs with variation, without replaying the plot. '
                         'Keep contact/recoil, a dance phrase or gag readable across edits.')
        else:
            lines.append('Edit on a change in action, attention or consequence, roughly 3–5 seconds when useful. '
                         'Keep contact/recoil, a dance phrase or gag readable across the cut; vary angle and distance '
                         'without resetting the event. Music accents are options, not compulsory cuts.')
    else:
        lines.append('Use a motivated longer take; reveal the change through blocking or camera movement rather than cuts.')
    if 'project_scope' in req and segment is not None:
        import json
        from banana_mv.mv_scope import clip_ending
        lines.append('SOURCE SCOPE / ENDING: '+json.dumps(clip_ending(req,segment),ensure_ascii=False))
    return '\n'.join(lines), primary



def clip_cinematography(req, mode, seconds, ending=None):
    """One relevant recipe for the compact writer; no duplicated scope/ledger."""
    if ending and ending.get('phase')=='terminal_hold':
        return 'Hold the established final composition with natural residual motion; introduce no new event.'
    lines=['Event -> character action -> attention -> camera -> edit. Keep geography and consequences readable.',
           'One main camera move per shot. Visible singing uses waist-up or closer; other events may use wider shots.',
           RECIPES[mode]]
    lines.append({'normal':'Use restrained movement; let the action breathe.',
                  'high':'Amplify purposeful movement and one motivated camera move.',
                  'extreme':'Emphasize a supported turning point with scale or speed contrast, then its reaction; intensity does not require constant speed.'}[req.get('intensity','high')])
    lines.append('Vary shot length with action and musical phrasing; no compulsory cut interval.'
                 if req.get('dynamic_cuts',True) else 'Prefer a motivated continuous take.')
    if seconds<=5:lines.append('Short interval: one readable beat or completion of an ongoing action.')
    return ' '.join(lines)
