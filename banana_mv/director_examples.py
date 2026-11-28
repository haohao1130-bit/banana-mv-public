"""Mode-specific examples of finished cinematic shot prose for the optional 35B.

Dance is adapted from the original successful project input (not the rewritten
H3 output). Action and the stage/boxing variants come from validated BANANAMV
renders. Other modes contain explicitly illustrative, unvalidated examples.
These examples teach detail and causal continuity, never assign current events.
"""
import re

VERSION = 'banana-director-examples-v3'
EXAMPLES = {
    "dance": {
        "cue": "A leads a confident dance exchange, B answers, both advance toward the audience. Continue the same arm gesture across a camera cut.",
        "body": "[Shot 1] Performer A launches from audience-left with a deep right diagonal step, drives his chest forward on the accent, sweeps both forearms outward above shoulder level and rebounds through a left cross-step. Performer B answers from audience-right with a wide grounded step, a sharp chest hit and an angular double-arm opening, both traveling toward the audience. Jacket panels lag behind the shoulder swing, then fall toward the hips as the knees compress. Red side illumination traces the advancing sleeves while the fixed runway strips streak past in perspective. Performer A sings with a predatory grin and looks straight into the approaching lens; Performer B watches him with a challenging stare and closed lips. A knee-height 24mm camera charges backward just ahead of their advancing shoes, then arcs toward Performer A's outside shoulder, moving close enough for his sweeping sleeve to cross the foreground. Cut through the sleeve while the arm continues outward.\n[Shot 2] At 00:04.080, Performer A completes the sweep and launches a waacking phrase, alternating large overhead arm circles with two grounded cross-steps. Performer B matches the foot accents with wide elbow strikes and a pronounced shoulder hit, then both open their feet into a broad stance. Fabric gathers at each bending elbow and releases as the arm extends. The fixed cold-white frame travels across the background only through camera parallax, while neutral fill preserves both faces. Performer A sings toward Performer B, eyebrows lifted in mocking delight; Performer B returns the gaze without singing. A close 28mm camera sweeps around Performer A from his front-left to his side, framing his face and upper torso as Performer B appears beyond the moving forearm. Cut on the outward elbow accent, before the feet recover.",
        "source": "Dangerous Contract V2, ACT01 SHOT01–02, original user input; performer labels generalized and word-count annotations removed. The cue is an editorial reconstruction."
    },
    "performance": {
        "cue": "A singer turns a restrained verse into a defiant address to the crowd.",
        "body": "[Shot 1] At the opening, the singer stands three-quarter to the audience with the microphone close to the mouth and the free hand resting against the side of the stand. As the assigned vocal phrase develops, the singer lifts the eyes from the floor, lets the shoulders settle and advances one deliberate step into the light. The free hand opens toward the audience, fingers relaxing rather than repeating a fist gesture. The jacket hem follows the step and settles against the hip; a narrow edge light separates the moving shoulder from the dark stage. The camera begins at chest height in a medium three-quarter view, travels alongside the step and closes toward the face, holding the singer's changing gaze as the gesture reaches its full extension. Cut on the change of attention, leaving the hand movement in progress.",
        "source": "New illustrative performance example; not a validated render."
    },
    "action": {
        "cue": "A calm martial master deflects a furious challenger with economical push-hands technique, then a flying kick turns the duel into a comic escape.",
        "body": "[Shot 1] Medium two-shot on a stone courtyard from a high slant angle behind Performer A's left shoulder, his robe and shawl filling the near foreground while Performer B stands mid-ground right, fists coiled. She launches a straight punch at his face; he snaps into a sideways hip turn, draws back his left forearm to glide under her fist and pushes it off with an open-palm deflection, chin tucked, eyes half-lidded and smirking as he sings. She recoils, jaw tightening, and switches to her right hand for a follow-up jab. The camera tracks backward rapidly along their exchange line, keeping both bodies and the sliding step connection in frame while sunlight glints off the contact point of sleeves and forearms.\n[Shot 2] At 00:01.760, low-angle wide shot from the side at ground level: Performer B steps forward with momentum and pushes a palm strike; Performer A crosses his left forearm in front of his chest to catch the palm, shoulders rolling together on impact, then slides laterally out of her range in a smooth sidestep. Her palm misses empty air; she plants her feet and turns to reorient toward his new position, arms snapping up. He lifts his gaze from her wrist to her eyes, grinning; she glares upward, teeth gritted. The camera trucks hard right to follow his escape vector, motion blur streaking the background pillars.\n[Shot 3] At 00:03.400, extreme low-angle close two-shot: he extends an open palm and their palms meet at the center of frame with a small recoil bounce; he rotates his waist, sweeping the pressed hands sideways while her forward inertia carries one more big step through the gap, fallen leaves skittering underfoot. Their palms drift apart as they pass at different depths; he holds eye contact, serene, while she narrows her eyes and steps closer. The camera pushes in fast on the clashing palms, then pops back out as they separate.",
        "source": "Banana Sect Abbot (大乘蕉宗住持), clip 05 shots 1–3, validated BANANAMV render; names generalized.",
        "keywords": "kung fu 功夫 wing chun 詠春 tai chi 太極 push hands 推手 palm 掌 deflect 化勁 monk 和尚 住持 martial arts 武術 courtyard"
    },
    "band": {
        "cue": "A guitarist plays an assigned phrase and catches the drummer's response.",
        "body": "[Shot 1] The guitarist leans into the instrument as the fretting hand shifts along the neck and the picking wrist continues its compact rhythmic path. The strap pulls taut across the shoulder when the player takes a half step toward the drummer, then relaxes as the weight settles. The guitarist glances across the stage rather than staring continuously at the lens. The drummer responds with a small nod and a visible stick rebound, staying behind the established kit. Warm side illumination follows the moving fingers while the rest of the stage remains in cool shadow. A close camera begins beside the guitar neck, travels toward the performer's expression, then reframes through the open space beyond the shoulder to reveal the drummer's response. The shot ends on their shared glance, preserving the ongoing playing action.",
        "source": "New illustrative band example; not a validated render."
    },
    "chase": {
        "cue": "A runner rounds a corner while a pursuer gains ground.",
        "body": "[Shot 1] The leading runner approaches the established corner at speed, eyes moving from the route ahead toward the opening on the right. The inside foot plants and the torso leans into the turn while the trailing arm follows the change in direction; loose fabric continues forward briefly before swinging around the hip. The pursuer enters the depth of frame on the same route, closing the gap but remaining behind. The camera tracks beside the lead at waist height, allowing the wall to slide through the near foreground and reveal the new corridor without changing the established travel direction. As the runner clears the corner, the framing opens enough to retain both performers' relative positions. Cut during the outgoing stride, so the next view resumes the same acceleration rather than replaying the turn.",
        "source": "New illustrative chase example; not a validated render."
    },
    "fantasy": {
        "cue": "An established magical object awakens and the character reacts.",
        "body": "[Shot 1] The character lowers an open hand toward the already established object, slowing just before contact as a faint light gathers within its surface. The fingertips meet the edge; the glow travels along the existing pattern and throws a moving reflection across the knuckles and nearby tabletop. The character draws a shallow breath, eyes following the advancing light, then shifts weight backward as the object visibly changes state. A sleeve follows the withdrawing wrist and settles against the forearm. The room retains its established geometry and light direction, with the new glow contributing a localized reflection instead of replacing the whole environment. A close camera starts at the hand and tracks the moving pattern, then rises toward the face in a continuous reveal. Hold the changed object and the character's reaction together at the end.",
        "source": "New illustrative fantasy example; not a validated render."
    },
    "story": {
        "cue": "A person recognizes a familiar object and quietly changes their mind.",
        "body": "[Shot 1] The person pauses beside the table with a hand still resting on the back of the chair. Their gaze settles on the familiar object, travels along its worn edge and returns to the other person seated across the table. A small breath lifts the chest; the fingers loosen around the chair as the guarded expression softens. The person draws the chair a little nearer and sits, keeping the object within reach, while the seated partner responds with a barely perceptible nod. The sleeve folds naturally at the elbow as the hand comes to rest. Soft window light remains consistent across both faces, and the shallow depth of field keeps the table's edge and the partner's silhouette in their established positions. An eye-level medium two-shot makes a gentle inward move as the decision becomes visible, then holds without a forced cut.",
        "source": "New illustrative quiet-drama example; not a validated render."
    },
    "horror": {
        "cue": "Someone notices a subtle anomaly in an established reflection.",
        "body": "[Shot 1] The character stops halfway through an ordinary hand movement as the reflection in the nearby glass catches their attention. The eyes shift first, followed by a small turn of the head; the supporting foot stays planted while the free hand lowers slowly. The glass and surrounding furniture retain their established positions. A faint change in the reflected shape becomes legible only as the character leans closer, and the face tightens in recognition rather than erupting into an immediate scream. The camera holds a restrained shoulder-height composition with the reflection in the far side of the frame, then makes a short lateral adjustment to bring the anomaly and the character's gaze into a clear spatial relationship. Existing light remains stable. Let the held reaction carry the suspense into the next beat.",
        "source": "New illustrative suspense example; not a validated render."
    },
    "comedy": {
        "cue": "A serious worker discovers that an ordinary prop has produced an absurd result.",
        "body": "[Shot 1] The worker finishes placing the established prop on the counter with the solemn concentration of a professional completing a delicate task. Their fingers release it one at a time; the shoulders straighten and the chin lifts in quiet satisfaction. The partner looks at the prop, then at the worker, holding the confused expression just long enough for the contrast to register. As the worker follows the partner's gaze, the smile fades into a tiny tightening of the mouth. A medium eye-level two-shot keeps the counter and both characters in clear relation; a modest sideways reframe reveals the absurd result that had been hidden behind the worker's elbow. The prop remains in its new position, the overhead light stays unchanged, and the worker's hand stops halfway through a second proud gesture. Hold the deadpan reaction rather than adding another unrelated gag.",
        "source": "New illustrative comedy example; not a validated render."
    }
}

# Additional validated renders, chosen over the mode default when the
# current style keys or event mention their keywords.
VARIANTS = [
    {
        "mode": "action",
        "cue": "A cocky mascot boxer overwhelms a stunned champion, intercut with singers driving the chorus on a festival stage.",
        "body": "[Shot 1] Inside the boxing arena, continuing from the previous frame: Performer A, the heavyweight champion, stumbles backward with his head thrown back, sweat glistening on his cheek, mouth open in shock as a red glove hovers near his jaw; he flails to raise his wrapped hands. The camera pulls back rapidly in front of him at high speed while Performer B charges into the foreground and closes in. Performer A is not singing; his mouth stays open in panic as he scrambles to re-guard.\n[Shot 2] At 00:02.300, ground-level push-in from Performer B's feet: he steps into Performer A's chest, right fist cocked at his waist, and the camera surges forward along his legs in a large, fast push-in. Cut as the fist begins its wind-up.\n[Shot 3] At 00:03.900, cut to the concert stage: the lead singer roars a line into the microphone, his free hand swinging a hard punch toward frame right. The camera whips right along the punch's path in a large, fast pan, cutting before the arm fully extends.\n[Shot 4] At 00:05.000, back in the arena: Performer B's right fist rockets into Performer A's midsection. The camera sits in an extreme close-up at A's side abdomen; the impact freezes into brief slow motion, torso folding, sweat flying, then snaps back to full speed as he doubles over, arms dropping.\n[Shot 5] At 00:06.400, Performer B lowers both hands, shrugs, shakes his head and grins smugly. The camera arcs quickly to a low angle in front of him, framing the satisfied smile as he looks down at the doubled-over champion.",
        "source": "Little Boxing King (小小拳王), clip 06 shots 1–5, validated BANANAMV render; names generalized.",
        "keywords": "boxing 拳擊 boxer 拳王 ring 擂台 jab uppercut hook punch 出拳 揮拳 knockout glove arena"
    },
    {
        "mode": "performance",
        "cue": "A cold rapper crosses a cabaret theater to take the microphone while his rival watches from the stage.",
        "body": "[Shot 1] At 00:01.333, low-angle tracking shot following Performer B: he grips a closed book in his left hand, steps out of the sofa and advances along the central aisle with deliberate, heavy footsteps. The camera slides backward at his pace, keeping him mid-shot as velvet seats blur into dark bokeh; his jaw stays set, gaze forward and unblinking.\n[Shot 2] At 00:02.000, extreme low-angle insert on his knee-high boots: a heel strikes the polished floor, the mirror reflection doubling the impact while dust motes catch the light; a subtle shake carries the weight without exaggeration.\n[Shot 3] At 00:02.667, hard cut to a frontal long-lens medium shot as he walks straight toward the lens, the aisle compressing into a shallow corridor of red seats behind him.\n[Shot 4] At 00:04.500, reverse cut to Performer A on stage, leaning against the moved high-back chair, arms loosely crossed, watching him approach with a playful, scheming grin.\n[Shot 5] At 00:06.500, tight insert at the base of the stage stairs: his boot lands on the first step, then the next, each strike crisp; the camera tilts up slowly as he ascends, matching the percussion.\n[Shot 6] At 00:07.000, side medium shot from stage right as he takes the last two steps and turns toward the microphone stand, the motion flowing straight on from the previous landing.",
        "source": "Max Power (最大功率), clip 06 shots 3–8, validated BANANAMV render; names generalized.",
        "keywords": "rap 饒舌 hip hop cabaret 歌舞廳 theater 劇場 stage entrance 登台 microphone mic 麥克風 walk aisle"
    },
]


def _hits(keywords, text):
    count = 0
    for word in keywords.lower().split():
        # Latin keywords match whole words ("mic" must not match "dynamic").
        pattern = r'\b' + re.escape(word) + r'\b' if word.isascii() else re.escape(word)
        count += bool(re.search(pattern, text))
    return count


def select_example(mode, style=''):
    """The mode default, or a validated variant whose keywords the style names."""
    text = str(style or '').lower()
    best, score = EXAMPLES.get(mode), 0
    for item in [EXAMPLES.get(mode) or {}] + [v for v in VARIANTS if v['mode'] == mode]:
        hits = _hits(item.get('keywords', ''), text)
        if hits > score:
            best, score = item, hits
    return best


def example_prompt(mode, style=''):
    item = select_example(mode, style)
    if not item:
        return ''
    return (
        'REFERENCE EXAMPLE — STYLE OF EXPANSION ONLY; NOT THE CURRENT COMMISSION\n'
        'Source: ' + item['source'] + '\n'
        'Example input (illustrative cue): ' + item['cue'] + '\n'
        'Example output (shot prose excerpt, not a complete six-section answer):\n'
        + item['body'] + '\nEND REFERENCE EXAMPLE\n'
        'Learn the causal connection between performance, material response, space, camera and edit. '
        'Apply this level of concrete invention to the actual current commission. '
        'The example performers, props, location, movement, lighting, lens, number of shots and cut times '
        'belong only to the example; design your own for the current event and requested intensity. '
        'Do not copy example text into the answer or reproduce its scene.'
    )
