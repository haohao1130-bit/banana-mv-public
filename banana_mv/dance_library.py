"""Compact dance knowledge, not motion capture or a compulsory choreography.
Taxonomy separates genre, mechanics, dynamics, composition, staging and music.
Original text references, informed by dance-analysis and music-conditioned
choreography concepts; not a copied or validated motion dataset.
"""
import math
import re

VERSION = 'banana-dance-library-v3'
DANCE_CATEGORIES = {
  "GENRE / movement vocabulary": [
    [
      "Hip Hop",
      "Grounded groove, bounce, rock and expressive footwork."
    ],
    [
      "Popping",
      "Controlled contractions and releases; separate chest and limb accents."
    ],
    [
      "Locking",
      "Loose funk groove alternating with abrupt locks and expressive points."
    ],
    [
      "Waacking",
      "Rhythmic shoulder-led arm circles, lines and theatrical expression."
    ],
    [
      "Vogue",
      "Angular arm frames, hand articulation and deliberately connected poses."
    ],
    [
      "Jazz Funk",
      "Jazz lines and rhythmic isolations combined with grounded pop choreography."
    ],
    [
      "House",
      "Elastic knee groove, light heel-toe and traveling footwork."
    ],
    [
      "Breaking",
      "Toprock, grounded transitions and floorwork where space and skill support them."
    ],
    [
      "Krump",
      "Expressive stomps, chest accents and forceful arm pathways."
    ],
    [
      "Contemporary",
      "Weight, suspension, release, reaching and grounded transitions."
    ],
    [
      "Ballet",
      "Alignment, turnout where appropriate, controlled rise and clear lines."
    ],
    [
      "Latin",
      "Rhythmic weight changes, grounded hip action and partner timing."
    ],
    [
      "Cabaret",
      "Theatrical gestures, deliberate reveal, jazz vocabulary and characterful timing."
    ],
    [
      "Dancehall",
      "Rhythmic grounded groove and torso articulation; respect its distinct vocabulary."
    ],
    [
      "Disco",
      "Traveling steps, expansive arm lines and upbeat groove."
    ],
    [
      "Ballroom",
      "Partner frame, shared timing and coordinated weight changes."
    ],
    [
      "Lyrical",
      "Expressive extensions and sustained phrases connected to musical intention."
    ],
    [
      "Musical theatre",
      "Character-led gestures, stylized walking and clear rhythmic phrasing."
    ]
  ],
  "MOVEMENT / physical building blocks": [
    [
      "Groove",
      "Continuous knee and torso pulse beneath gestures."
    ],
    [
      "Bounce",
      "Compress and release through knees with supported feet."
    ],
    [
      "Rock step",
      "Transfer weight away and back without losing the base."
    ],
    [
      "Cross-step",
      "Pass one foot across the other, then transfer weight."
    ],
    [
      "Chasse",
      "Step, close, step with a readable traveling direction."
    ],
    [
      "Heel-toe",
      "Alternate heel and toe support and rotate through the feet."
    ],
    [
      "Glide",
      "Support on one foot while the free foot slides; preserve contact."
    ],
    [
      "Side step",
      "Open laterally and collect the trailing foot."
    ],
    [
      "Pivot",
      "Turn over a supporting foot, land with a clear direction."
    ],
    [
      "Jazz turn",
      "Gather arms, spot where appropriate and recover balance."
    ],
    [
      "Lunge",
      "Bend a supporting knee while extending the other leg."
    ],
    [
      "Rebound",
      "Return from compression into the next phrase."
    ],
    [
      "Chest hit",
      "Brief chest contraction and release on an accent."
    ],
    [
      "Shoulder isolation",
      "Move one or both shoulders against a stable torso."
    ],
    [
      "Elbow accent",
      "Drive an articulated elbow line and release."
    ],
    [
      "Wrist flourish",
      "Lead a small arc through wrist and fingers."
    ],
    [
      "Arm circle",
      "Sweep through a defined shoulder-led path."
    ],
    [
      "Arm wave",
      "Pass a wave sequentially through adjacent arm joints."
    ],
    [
      "Body wave",
      "Sequence chest, ribs, pelvis and knees coherently."
    ],
    [
      "Lock and release",
      "Resolve a crisp shape then return into motion."
    ],
    [
      "Open and close",
      "Expand a limb frame and gather it with weight control."
    ],
    [
      "Reach and retract",
      "Extend toward a target and return along a clear path."
    ],
    [
      "Hip isolation",
      "Articulate pelvis over stable support."
    ],
    [
      "Head accent",
      "Small motivated head direction or nod linked to rhythm."
    ],
    [
      "Rise and lower",
      "Use ankle and knee extension, then controlled descent."
    ],
    [
      "Jump and land",
      "Show preparation, flight, soft landing and recovery."
    ],
    [
      "Floor transition",
      "Lower with support and recover without teleporting."
    ],
    [
      "Weight transfer",
      "Identify supporting foot, moving foot and resulting balance."
    ]
  ],
  "DYNAMICS / movement quality": [
    [
      "Strong",
      "Decisive muscular intention, grounded force."
    ],
    [
      "Light",
      "Buoyant, delicate weight and contact."
    ],
    [
      "Sudden",
      "Brief decisive time accent."
    ],
    [
      "Sustained",
      "Continuous movement developing over time."
    ],
    [
      "Direct",
      "Focused path toward a clear destination."
    ],
    [
      "Indirect",
      "Curved or multi-directional attention and path."
    ],
    [
      "Bound",
      "Controlled flow and intentional braking."
    ],
    [
      "Free",
      "Released flow with follow-through."
    ],
    [
      "Suspension",
      "Momentary held extension before recovery."
    ],
    [
      "Elastic",
      "Compression and rebound linked through the body."
    ],
    [
      "Percussive",
      "Discrete accents separated by release."
    ],
    [
      "Fluid",
      "Connected transitions without discontinuous resets."
    ]
  ],
  "CHOREOGRAPHY / phrase and relationships": [
    [
      "Unison",
      "Shared phrase and timing with individual performance texture."
    ],
    [
      "Mirror",
      "Reflect directions while preserving shared rhythm."
    ],
    [
      "Canon",
      "Stagger the start of a shared phrase."
    ],
    [
      "Counterpoint",
      "Distinct compatible phrases create a readable dialogue."
    ],
    [
      "Call and response",
      "One performer initiates; another answers."
    ],
    [
      "Lead exchange",
      "Transfer initiative through a visible transition."
    ],
    [
      "Motif",
      "Build a recognizable short action phrase."
    ],
    [
      "Variation",
      "Change direction, scale, timing or formation of an existing motif."
    ],
    [
      "Reprise",
      "Return to a motif where music or narrative motivates it."
    ],
    [
      "Contrast",
      "Juxtapose distinct movement qualities."
    ],
    [
      "Accumulation",
      "Build a phrase by adding linked elements over time."
    ],
    [
      "Cross and exchange",
      "Pass on separate spatial paths and swap positions."
    ],
    [
      "Formation transition",
      "Move from one clear formation into another."
    ],
    [
      "Levels",
      "Use high, middle and low positions when motivated."
    ],
    [
      "Isolation and ensemble",
      "Foreground one performer while others maintain meaningful support."
    ],
    [
      "Spatial echo",
      "Repeat a shape in a different part of the space."
    ],
    [
      "Continuous phrase",
      "Carry unfinished motion through shot and clip boundaries."
    ],
    [
      "Resolution",
      "Complete a phrase at a meaningful musical or story point."
    ]
  ],
  "STAGING / performance format": [
    [
      "Solo",
      "Maintain one performer's intention and personal space."
    ],
    [
      "Duet",
      "Coordinate spacing, attention, initiative and physical responses."
    ],
    [
      "Group",
      "Give performers legible lanes, roles and formation transitions."
    ],
    [
      "Dance battle",
      "Alternating initiative and response without inventing a physical fight."
    ],
    [
      "Runway",
      "Use the established axis and traveling presentation."
    ],
    [
      "Chair choreography",
      "Use an established chair as anchor; coordinate approach, contact and release."
    ],
    [
      "Pole choreography",
      "Use an established pole and believable support; no unexplained grips or aerial resets."
    ],
    [
      "Prop choreography",
      "Let an existing prop shape interaction, not create unrelated events."
    ],
    [
      "Partner hold",
      "Coordinate existing contact, balance and release."
    ],
    [
      "Concert dance",
      "Preserve singing duties while movement continues."
    ],
    [
      "Musical scene",
      "Let character action motivate dance inside the assigned event."
    ],
    [
      "Ensemble entrance",
      "Establish spatial routes and staggered arrivals only if assigned."
    ],
    [
      "Floor-based performance",
      "Use available floor space and clear support transitions."
    ],
    [
      "Seated performance",
      "Express rhythm through compatible upper-body and supported leg motion."
    ]
  ],
  "MUSICALITY / timing choices": [
    [
      "Beat",
      "Use measured or authored pulse when available."
    ],
    [
      "Downbeat",
      "Anchor phrase starts to supported strong metrical positions."
    ],
    [
      "Backbeat",
      "Use backbeat accents only when the source supports them."
    ],
    [
      "Offbeat",
      "Place a gesture between main beats where musically motivated."
    ],
    [
      "Syncopation",
      "Contrast expected pulse and actual accent without inventing evidence."
    ],
    [
      "Eight-count",
      "Organize phrases across eight counts when meter and tempo support it."
    ],
    [
      "Half-time feel",
      "Broaden motion over multiple beats when appropriate."
    ],
    [
      "Double-time feel",
      "Use compact subdivisions without forcing impossible speed."
    ],
    [
      "Accent",
      "Align a visible hit or release with an available musical cue."
    ],
    [
      "Sustain",
      "Let a gesture extend through a longer phrase."
    ],
    [
      "Pause",
      "Hold a meaningful state through an actual or authored break."
    ],
    [
      "Pickup",
      "Prepare motion before the next supported accent."
    ],
    [
      "Phrase boundary",
      "Use music structure as a soft guide, not a compulsory cut."
    ],
    [
      "Verse development",
      "Establish or develop a motif when the supplied structure supports it."
    ],
    [
      "Chorus reprise",
      "Recall an established phrase when the chorus returns."
    ],
    [
      "Instrumental variation",
      "Develop movement without assigning invented vocals."
    ],
    [
      "Tempo change",
      "Adjust phrase scale to measured or explicitly authored tempo changes."
    ],
    [
      "Across-cut timing",
      "A camera cut changes viewpoint, not the dance count."
    ]
  ]
}

# Conservative literal phrase matches in delivered shot prose; these are not
# visual recognition and do not infer choreography from a filename or genre.
MOTIF_TERMS = {
    'Waacking': r'waack(?:ing)?',
    'Popping': r'popping',
    'Locking': r'locking',
    'Glide': r'glid(?:e|es|ing)',
    'Cross-step': r'cross[- ]steps?',
    'Heel-toe': r'heel[- ]toe',
    'Chasse': r'chass[eé]',
    'Body wave': r'body wave',
    'Arm wave': r'arm wave',
    'Arm circle': r'arm circles?',
    'Chest hit': r'chest (?:hits?|accents?|locks?)',
    'Shoulder hit': r'shoulder (?:hits?|accents?)',
    'Pivot': r'pivot(?:s|ing)?',
    'Mirror': r'mirror(?:ed|ing)?',
    'Canon': r'canon',
    'Vogue': r'vogue',
}

def shot_bodies(prompt):
    if not isinstance(prompt, str):
        return []
    detail = re.split(r'(?im)^\s*detailed_description\s*:', prompt, maxsplit=1)
    if len(detail) != 2:
        return []
    text = re.split(r'(?im)^\s*(?:overall_soundscape|non_diegetic_music)\s*:', detail[1], maxsplit=1)[0]
    return [p.strip() for p in re.split(r'(?i)\[Shot\s+\d+\]', text)[1:] if p.strip()]

def dance_memory(history, current_index):
    """Only selected, completed previous dance prompts, never future plans."""
    counts = {}
    last = ''
    for index, prompt in history:
        if index >= current_index:
            continue
        bodies = shot_bodies(prompt)
        if not bodies:
            continue
        text = ' '.join(bodies)
        for name, pattern in MOTIF_TERMS.items():
            if re.search(r'\b(?:' + pattern + r')\b', text, re.I):
                counts[name] = counts.get(name, 0) + 1
        if index == current_index - 1:
            # Last shot is a *written intention*, not verified physical pose.
            last = re.sub(r'<Picture\s+\d+>', '[earlier reference]', bodies[-1], flags=re.I)
            last = re.sub(r'^At\s+\d+:\d+(?:\.\d+)?,\s*', '', last, flags=re.I)
            if len(last) > 1400:
                tail = last[-1400:]
                split = re.search(r'[.!?]\s+', tail)
                last = tail[split.end():] if split else tail
    return {'motifs': sorted(counts.items(), key=lambda p: (-p[1], p[0]))[:12],
            'previous_last_shot': last,
            'source': 'selected completed prompt text; not video-verified'}

def _number(value, low, high):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high

def audio_context(segment):
    e = segment.get('audio_evidence') or {}
    if not isinstance(e, dict):
        return ''
    duration = float(segment.get('seconds', 15))
    structure = e.get('music_structure') or {}
    pulse = e.get('pulse_estimate') or {}
    structure = structure if isinstance(structure, dict) else {}
    pulse = pulse if isinstance(pulse, dict) else {}
    rows = []
    for label, val in [('Predicted BPM', structure.get('bpm')), ('Pulse estimate BPM', pulse.get('bpm_estimate'))]:
        if _number(val, 20, 400):
            rows.append(f'{label}: {val:g}')
    if pulse.get('ambiguous_half_double_tempo'):
        rows.append('Pulse estimate has half/double-tempo ambiguity.')
    energy = e.get('relative_energy')
    if energy in ('low', 'medium', 'high'):
        rows.append('Measured relative energy: ' + energy)
    for label, values in [('Predicted beats', structure.get('beats_s')), ('Predicted downbeats', structure.get('downbeats_s')), ('Transient candidates', e.get('transient_candidates_s'))]:
        if isinstance(values, (list, tuple)):
            times = [f'{v:.3f}' for v in values if _number(v, 0, duration)][:64]
            if times:
                rows.append(label + ' (local seconds): ' + ', '.join(times))
    for item in structure.get('sections') or []:
        if not isinstance(item, dict):
            continue
        a, b, label = item.get('start_s'), item.get('end_s'), item.get('predicted_label')
        if _number(a,0,duration) and _number(b,a,duration) and isinstance(label,str) and re.fullmatch(r'[a-zA-Z_-]{1,24}',label):
            rows.append(f'Predicted section {a:.3f}–{b:.3f}s: {label}')
    return ('CURRENT CLIP MUSIC EVIDENCE — estimates only, not heard audio or mandatory cut times:\n' + '\n'.join(rows)
            + '\nUse the author\'s timing and actual available evidence; preserve the original song.') if rows else ''

def dance_prompt(segment):
    sections = [
        'DANCE KNOWLEDGE ' + VERSION + ': Choose the genre and physical vocabulary from the actual shared setup, current event, music evidence, performers, space and incoming state. All categories are references, not a playlist, required items or a closed vocabulary. Compose compatible phrases, preserve a signature motif when music calls for reprise, and vary expression, formation and camera rather than forcing new steps. A prop or partner technique applies only when the corresponding prop or partner is established. Use the existing beat, weight and momentum to choose transitions. Deepen physical description without overloading the time.',
    ]
    for category, items in DANCE_CATEGORIES.items():
        sections.append(category + '\n' + '\n'.join(name + ': ' + desc for name, desc in items))
    music = audio_context(segment)
    if music:
        sections.append(music)
    memory = segment.get('dance_memory') or {}
    if memory.get('motifs') or memory.get('previous_last_shot'):
        rows = ['PAST DANCE REFERENCE — completed selected prompt text, not visual observation. Use this only for continuity and intentional motif reprise, never to replay prior events. Current event and attached actual frame(s) override earlier written intention.']
        if memory.get('motifs'):
            rows.append('Previously named movement vocabulary (number of completed clips mentioning it; not confirmed signature choreography): ' + ', '.join(f'{name} ({count})' for name,count in memory['motifs']))
        if memory.get('previous_last_shot'):
            rows.append('Previous clip final shot, written intention only (old local timing and references are not current): ' + memory['previous_last_shot'])
        sections.append('\n'.join(rows))
    return '\n\n'.join(sections)
