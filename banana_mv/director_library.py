"""Original lightweight creative reference library for the optional 35B MV director.

Text knowledge, not motion-capture assets or a required camera recipe.
No inference call, vector store, H3 trigger mutation, or acceptance gate.
"""
from banana_mv.director import MODES, RECIPES
from banana_mv.activity_router import route_activity
from banana_mv.core import normalize_action_loras

VERSION = 'banana-director-library-v3.1'
MODE_LIBRARY = {
    "dance": [
        ["Waacking","Rhythmic arm pathways circle around the head and shoulders; grounded weight shifts and sharp accents finish each arc.","waacking arm 手臂"],
        ["Popping and hits","Short muscular contractions punctuate controlled releases; isolate chest, shoulders and elbows without freezing the entire body.","popping hit 機械"],
        ["Locking","Loose groove opens into a crisp lock and a playful point, then releases back into traveling footwork.","locking 鎖"],
        ["Body wave","Sequence chest, ribs, pelvis and knees into a connected wave; let the weight settle before redirecting.","wave 波浪"],
        ["Glide","Transfer weight to the supporting foot as the free foot slides; preserve contact and show the illusion of effortless travel.","glide slide 滑步"],
        ["House footwork","Alternate light grounded steps, heel-toe pivots and elastic knee rebounds with a traveling groove.","house footwork 腳步"],
        ["Vogue lines","Shape angular arm frames, deliberate wrist paths and expressive poses, with clear transitions and stable footing.","vogue pose"],
        ["Jazz turn","Spot the gaze, gather the arms and pivot over a supporting foot; open the shoulders on landing.","turn spin 旋轉"],
        ["Partner counterpoint","Give the lead a readable phrase and the partner a distinct rhythmic answer; trade initiative without mirroring by default.","partner duo duet 對決 雙人"],
        ["Mirror and canon","Repeat a shared phrase in mirrored geometry or stagger its timing; preserve individual character and rejoin on an earned accent.","mirror canon 同步"],
        ["Cross and exchange","Travel on offset paths, pass shoulder to shoulder with safe clearance, exchange foreground/background and continue the phrase.","cross exchange 交錯 換位"],
        ["Prop choreography","Use an established prop as a spatial anchor; approach, redirect around it, release contact and transfer weight naturally.","chair pole 椅 鋼管 道具"],
    ],
    "action": [
        ["Guard and measure","Read distance, establish a balanced guard and a clear line of attention; use a feint to draw a visible defensive response.","guard feint 拳擊"],
        ["Evasion and redirect","Shift the head and torso off the incoming line, transfer weight and recover facing the opponent.","dodge evade 閃避"],
        ["Exchange of advantage","Show an attack, a defense and a character-specific response; change spacing and initiative as a readable result.","counter fight 攻防"],
        ["Contact and recoil","Make the cause of contact, body recoil, balance recovery and changed positions legible; use cinematic non-instructional staging.","impact hit 受擊"],
        ["Footwork under pressure","Use lateral steps and pivots to change the line of confrontation; preserve the opponent's relative position.","footwork pivot 步法"],
        ["Obstacle interaction","Let established scenery redirect movement or provide cover; show the object's response and preserve its changed state.","obstacle prop 障礙"],
        ["Recovery beat","After a decisive motion, show breath, stance recovery, reassessment and the next intention rather than restarting.","recovery 起身"],
        ["Feint and reaction","A visible preparatory motion changes the other performer's attention; resolve the exchange in a coherent direction.","feint 假動作"],
    ],
    "performance": [
        ["Vocal intention","Give each sung phrase a visible intention toward a person, object or audience, not generic facing the camera.","sing vocal 演唱"],
        ["Microphone blocking","Coordinate grip, breath, free-hand gestures and stance changes; follow the assigned vocal role.","mic 麥克風"],
        ["Stage travel","Move between motivated positions with a readable destination and an audience or partner reaction.","stage walk 舞台"],
        ["Call and response","Exchange gaze and expression between assigned performers; keep mouth movement appropriate to source roles.","duet partner 對唱"],
        ["Intimate phrase","Use breath, eyes, jaw and small torso changes to carry an emotional line without inventing dialogue.","quiet close 抒情"],
        ["Crowd-scale payoff","When the scene supports it, contrast the performer with audience scale and motivated lighting response.","crowd concert 觀眾"],
        ["Performance insert","Reveal a meaningful hand, prop, gaze or environmental response that advances the current event.","insert prop 特寫"],
        ["Motif variation","Return to a recognizable performance gesture with changed angle, intensity or emotional meaning.","chorus motif 副歌"],
    ],
    "band": [
        ["Guitar phrase","Coordinate fretting and picking with the visible musical phrase; instrument strap and hand positions remain plausible.","guitar 吉他"],
        ["Bass groove","Use grounded body rhythm, plausible fret-hand shifts and restrained plucking; interact with the rhythmic section.","bass 貝斯"],
        ["Drum accent","Show a prepared stick path, credible contact, rebound and coordinated body rhythm without inventing the heard notes.","drum 鼓"],
        ["Keyboard gesture","Keep fingers oriented to the keys and hands in a plausible register; make posture and gaze react to the phrase.","keyboard piano 鍵盤"],
        ["Ensemble exchange","Transfer attention between existing musicians through eye contact, nods and rhythmic physical response.","band ensemble 樂團"],
        ["Solo coverage","Reveal an assigned featured player through instrument detail, face and full playing posture; return to ensemble context.","solo 獨奏"],
        ["Stage geography","Keep musician positions, instruments, cables and sightlines consistent while choosing contrasting viewpoints.","stage 舞台"],
        ["Instrument reaction","A string vibration, cymbal motion or performer response may become an insert when visually motivated.","instrument insert"],
    ],
    "chase": [
        ["Directional pursuit","Establish pursuer, target and travel vector; maintain their distance relationship as it changes.","chase pursuit 追逐"],
        ["Corner reveal","Reveal the next route through a motivated turn or foreground pass; preserve the destination across the edit.","corner turn 轉角"],
        ["Obstacle choice","Show a readable decision to go around, under or over an existing obstacle, then its effect on separation.","obstacle 障礙"],
        ["Acceleration and brake","Show increasing stride or vehicle momentum, then credible braking, body lean and recovery.","speed brake 加速"],
        ["Near escape","Make an opportunity and reaction visible without resetting the pursuer to an earlier position.","escape 逃"],
        ["Parallel coverage","Alternate target and pursuer with consistent screen direction and landmarks.","parallel intercut"],
        ["Moving viewpoint","Use a lateral tracking or rear-follow view to express relative speed and parallax.","tracking 跟拍"],
        ["Aftermath","Let stopping, breath, glance back and changed spacing reveal the current outcome.","stop breath 停"],
    ],
    "fantasy": [
        ["Power preparation","Make an authorized ability originate from a visible intention, gesture or established object.","magic power 魔法"],
        ["Transformation continuity","Connect the original form to its altered state through a readable material or silhouette change.","transform 變身"],
        ["Energy propagation","Trace an established visual effect from source through space to its visible consequence.","energy beam 能量"],
        ["Unusual anatomy","Respect the declared body form and its feasible support, movement and balance rather than adding human limbs.","snake creature 蛇"],
        ["Environment response","Let light, dust, fabric, water or nearby objects react to the event's visible physical effects.","water dust 水"],
        ["Scale revelation","Use foreground comparison or gradual reveal to establish the scale of an authorized creature or phenomenon.","scale giant 巨大"],
        ["Wonder or fear","Show the character noticing, evaluating and responding to an extraordinary change.","wonder reaction"],
        ["Persistent result","Carry the changed physical state and its emotional consequences into the next beat.","aftermath 結果"],
    ],
    "story": [
        ["Choice and consequence","Make the character decide and act on an immediate objective; reveal a concrete change in the scene.","choice decision 選擇"],
        ["Eyeline exchange","Establish who notices what, then show the other person's or object's meaningful reaction.","look gaze 眼神"],
        ["Object business","Use a familiar prop through purposeful hand contact; let its changed placement carry narrative meaning.","prop object 道具"],
        ["Emotional turn","Progress from one visible expression, breath or posture to another as the event alters understanding.","emotion 情緒"],
        ["Approach and withdrawal","Change interpersonal distance through a motivated step or hesitation; let the partner respond.","approach distance 靠近"],
        ["Quiet reveal","Reveal new information through a restrained reframing, gaze or deliberate gesture.","reveal 發現"],
        ["Everyday action","Show the practical sequence of handling, setting down or moving an object without padding the event.","daily cook 料理"],
        ["Held reaction","Stay with a meaningful reaction long enough to read it; choose a cut only when the viewpoint adds value.","reaction 沉默"],
    ],
    "horror": [
        ["Offscreen attention","Let a character notice an established anomaly outside frame; reveal its location through a motivated eyeline.","offscreen 聲響"],
        ["Partial reveal","Use occlusion or shadow to reveal only the part that matters; make the change legible.","shadow reveal 陰影"],
        ["Negative space","Compose a meaningful empty region and let attention migrate toward it.","space 空間"],
        ["Subtle anomaly","A small object, reflection or environment change earns a second look before escalation.","anomaly reflection 異常"],
        ["Approach under tension","Use careful steps and interrupted movement; let posture communicate uncertainty.","approach 緊張"],
        ["Reaction before reveal","Show recognition through eyes, breath and stillness before giving the audience the relevant information.","reaction 恐懼"],
        ["Spatial uncertainty","Preserve actual scene geography while withholding a viewpoint for suspense.","suspense 懸疑"],
        ["Controlled release","Resolve the current reveal with a readable consequence rather than unrelated shock or violence.","release 結果"],
    ],
    "comedy": [
        ["Deadpan contrast","Play an absurd event with completely serious behavior; let the visual contradiction carry the joke.","deadpan 一本正經"],
        ["Setup and payoff","Establish the expectation with a readable action; reveal its surprising consequence at the right moment.","payoff 梗"],
        ["Reaction delay","Hold a short moment of comprehension before a character's distinct physical or facial reaction.","reaction 驚訝"],
        ["Prop reversal","Use an established object in an unexpected but coherent way; show the result without resetting it.","prop 道具"],
        ["Escalation","Develop the same comic problem through a new consequence instead of introducing unrelated gags.","escalation"],
        ["Status contrast","Contrast the confident character's behavior with the other's response and changed power dynamic.","contrast"],
        ["Reveal by reframing","Let a pullback, foreground pass or contrasting view uncover the visual joke.","reveal 拉遠"],
        ["Comic aftermath","Give the visual payoff room to register; preserve the physical result for the next event.","aftermath"],
    ],
}
CAMERA_LIBRARY = [
    ["Low tracking pass","Begin near floor level and travel beside grounded motion; use parallax to emphasize speed and body path.","dance action chase"],
    ["Close orbit","Arc around a motivated subject or pair with a clear start/end view; preserve their spatial relationship.","dance action fantasy"],
    ["Decisive push-in","Advance toward a changing expression or consequential gesture, ending at the meaningful detail.","performance story horror comedy action"],
    ["Shoulder reverse","Use an over-shoulder view and opposing angle to clarify attention, interaction and distance.","story action dance horror comedy"],
    ["Full-body moving coverage","Keep feet, body path and partner spacing visible while traveling with the action.","dance action chase"],
    ["Extreme close insert","Isolate a meaningful eye, hand, instrument or physical accent; cut back with continuity.","performance band dance story horror"],
    ["Hero low angle","Use a low perspective and decisive composition at an earned moment of confidence or reversal.","action dance performance fantasy"],
    ["Foreground pass","Track behind an established foreground object to reveal another view or change focus.","dance chase comedy fantasy horror"],
    ["Lateral truck","Move parallel to the subject so background displacement and relative motion remain readable.","dance action chase band"],
    ["Static tension","Hold a precisely composed view while the action, attention or emotion changes inside it.","story horror comedy"],
    ["Wide spatial reveal","Use a wide or pullback view to establish geography, ensemble scale or an unexpected relationship.","fantasy band comedy chase dance"],
    ["Intimate eye-level follow","Move subtly with a performer at eye level to maintain emotional proximity without unnecessary spectacle.","story performance horror"],
]
EDIT_LIBRARY = [
    ["Match on action","Cut during one unfinished motion, resume the same motion and direction in the new view.","dance action chase band"],
    ["Accent cut","Cut on a supported musical or physical accent; an accent can also be expressed without a cut.","dance performance band action"],
    ["Occlusion transition","Use a real passing foreground shape to conceal a motivated viewpoint change.","dance chase fantasy comedy"],
    ["Reaction cut","Show the receiver's distinct response at the moment it changes understanding.","story comedy horror action performance"],
    ["Parallel montage","Alternate established separate events using visual or rhythmic correspondence without merging locations.","story performance band chase"],
    ["Contrast cut","Juxtapose scale, emotion or expectation when the new viewpoint advances the event.","comedy story fantasy"],
    ["Held take","Let a coherent performance or emotional change unfold without unnecessary cuts.","story horror dance"],
    ["Detail to geography","Connect a meaningful insert to the wider scene so the viewer understands its consequence.","band action story fantasy"],
]
ACTING_LIBRARY = [
    ["Intent and attention","Give a specific gaze target and intention before a gesture or movement.","all"],
    ["Emotional counterpoint","Give partners distinct simultaneous reactions; avoid identical poses and expressions.","dance story comedy action performance"],
    ["Micro-expression","Let eyes, jaw, brow or breath shift in response to a concrete event.","story horror performance comedy"],
    ["Confidence and challenge","Use deliberate posture, controlled smile and spatial initiative appropriate to the character.","dance action performance"],
    ["Physical recovery","Show weight settling, breath, follow-through and a changed stance after motion.","action dance chase"],
    ["Restrained recognition","Let a small pause or altered eye line carry recognition without melodrama.","story horror comedy"],
    ["Ensemble awareness","Use plausible glances and coordinated timing between already present performers.","band dance performance"],
]
VISUAL_LIBRARY = [
    ["Layered depth","Use foreground, subject plane and background with motivated separation and parallax.","all"],
    ["Directional light","Use established light direction to reveal faces, movement and material response.","all"],
    ["Silhouette and rim","Use motivated backlight to clarify body shape or scale, not obscure identity.","dance performance fantasy"],
    ["Texture and inertia","Let fabric, props, dust or water respond to actual movement without unrelated effects.","dance action fantasy chase"],
    ["Negative space","Place empty space where attention, suspense or a comic reveal needs it.","story horror comedy"],
]

LORA_HINTS = {
    'dance': 'Dance adapter is mounted; describe a coherent movement phrase and its visible body mechanics.',
    'beat_sync': 'Beat-sync adapter is mounted; use available rhythm evidence for accents without inventing exact beats.',
    'choreography': 'Choreography adapter is mounted; give dancers clear spatial relationships, phrase progression and transitions.',
    'combat': 'Combat adapter is mounted; preserve readable preparation, exchange and reaction.',
    'fight_flow': 'Fight Flow adapter is mounted; preserve spatial continuity and changing initiative.',
    'repair': 'Motion Repair adapter is mounted; preserve momentum, balance and recovery.',
}


def select_mode(req, segment):
    """Re-evaluate local activity, including previously saved auto plans."""
    row = segment.get('director_plan') or {}
    planned = row.get('mode') or segment.get('director_mode') or 'story'
    return route_activity(row.get('event', ''), req.get('director', 'auto'), planned)


def _rank(entries, mode, event, index, limit, tagged=False):
    # Relevance first. Rotate ties across clips to vary the *suggestions*, not
    # the actual action/camera decisions. No global storyline is inspected.
    event = event.lower()
    def score(pair):
        pos, (_, _, tags) = pair
        relevant = ((2 if mode in tags.split() else 1 if 'all' in tags.split() else 0)
                    if tagged else sum(1 for tag in tags.lower().split() if tag in event))
        return (-relevant, (pos - index) % len(entries))
    return [entry for _, entry in sorted(enumerate(entries), key=score)[:limit]]


def _format(title, entries):
    return title + '\n' + '\n'.join('- ' + name + ': ' + description
                                    for name, description, _ in entries)


def build_library(req, segment):
    """Return a short, clip-specific advisory block and diagnostic metadata."""
    mode = select_mode(req, segment)
    row = segment.get('director_plan') or {}
    event = str(row.get('event') or '')
    index = int(segment.get('index', 0))
    # Existing action adapters remain independent from genre knowledge.
    raw = req.get('action_loras')
    active = []
    if isinstance(raw, dict):
        loras = normalize_action_loras(raw)
        active = [key for key in LORA_HINTS if loras.get(key, {}).get('enabled')]
    from banana_mv.dance_library import VERSION as DANCE_VERSION, DANCE_CATEGORIES, dance_prompt, audio_context
    movement = (dance_prompt(segment, include_music=False) if mode == 'dance' else
                _format('MOVEMENT / STAGING INGREDIENTS', _rank(MODE_LIBRARY[mode], mode, event, index, 7)))
    sections = [
        'BANANA DIRECTOR LIBRARY ' + VERSION + ' | selected specialty: ' + mode,
        'CREATIVE METHOD: Read the current event and incoming physical state first. Expand the event into a coherent local performance: intention, body actions, partner responses, momentum, consequence. Then design the camera, lighting and editing that best reveal that performance. Commit those decisions to complete native H3 shot prose, not just reasoning.',
        'The following are optional creative ingredients, not a required sequence, vocabulary restriction, shot quota or permission to add unrelated events. Adapt, combine or invent better choices. Apply a specialty only to the activity actually occurring in this clip. Honor the current commission, continuity, timing, cast, wardrobe, audio and any locked camera choices. Do not replay completed action.',
        'SPECIALTY: ' + MODES[mode] + ' ' + RECIPES[mode],
        movement,
        _format('CAMERA INGREDIENTS', _rank(CAMERA_LIBRARY, mode, event, index, 4, True)),
        _format('EDITING INGREDIENTS', _rank(EDIT_LIBRARY, mode, event, index, 3, True)),
        _format('PERFORMANCE INGREDIENTS', _rank(ACTING_LIBRARY, mode, event, index, 3, True)),
        _format('VISUAL INGREDIENTS', _rank(VISUAL_LIBRARY, mode, event, index, 2, True)),
    ]
    music = audio_context(segment) if req.get('audio_analysis', True) else ''
    if music:
        sections.append(music)
    if active:
        sections.append('ACTIVE DOWNSTREAM ADAPTERS (capability hints, not verified trigger words):\n' +
                        '\n'.join('- ' + LORA_HINTS[key] for key in active) +
                        '\nPython owns actual adapter mounting and any established trigger words. No new trigger words.')
    if not req.get('dynamic_cuts', True):
        sections.append('The user disabled dynamic editing: favor coherent takes; cut only as the event or explicit instructions warrant.')
    if req.get('intensity') == 'normal':
        sections.append('Natural intensity: use precise, motivated restraint; do not force energetic camera moves.')
    if float(segment.get('seconds', 10)) <= 5:
        sections.append('Short interval: prioritize a clear ongoing beat and its consequence; ingredients are alternatives, not a checklist.')
    text = '\n\n'.join(sections)
    info = {'version': VERSION, 'mode': mode, 'active_loras': active,
            'music_evidence': bool(music),
            'words': len(text.split())}
    if mode == 'dance':
        info.update(dance_version=DANCE_VERSION,
                    dance_entries=sum(len(items) for items in DANCE_CATEGORIES.values()),
                    dance_categories=len(DANCE_CATEGORIES))
    return text, info


def creative_prompt(system, req, segment):
    """Used only by 35B's creative drafting routes; no new call or validation."""
    block, info = build_library(req, segment)
    from banana_mv.director_examples import VERSION as EXAMPLE_VERSION, example_prompt
    example = example_prompt(info['mode'])
    info['example_version'] = EXAMPLE_VERSION
    info['example_mode'] = info['mode'] if example else None
    info['example_words'] = len(example.split())
    segment['director_library'] = info
    return system + '\n\n' + block + ('\n\n' + example if example else '')
