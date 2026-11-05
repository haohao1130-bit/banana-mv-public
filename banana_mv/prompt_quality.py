"""Reference, scene and clip-scope generation guidance; no semantic veto."""
import re


def director_led(req):
    return bool(req.get('director_authority') and req.get('story_plan',True) and req.get('rewrite',True))


DIRECTOR_AUTHORITY = (
    'DIRECTOR-LED MV: You have creative authority over story rhythm, montage, shot order, event density '
    'and the balance of performance and story. Treat the user outline as creative material, not a shot-by-shot '
    'execution script. Use the whole-song measured music profile to reorder, condense, expand or restage '
    'compatible developments, choose visual contrasts and shape peaks. Complement the selected main style '
    'with suitable scene modes as needed. Do not force each paragraph into its own clip. Preserve source audio, '
    'reference identities, assigned singing/non-singing roles and explicit non-negotiable restrictions. '
    'Do not rename characters or impose a fixed cast, gender or single-person setup. Requested ending ideas '
    'are creative anchors whose pacing and staging can change; explicitly locked outcomes or terminal shots '
    'remain constraints. No separate semantic judge vetoes your creative interpretation.'
)


MV_POLICY = (
    'MUSIC VIDEO FIRST: The source song is the continuous master timeline; visual events serve the MV. '
    'Use measured musical dynamics, accents, pauses and user-supplied section/lyric context to choose each '
    'clip function: vocal performance, story/action, interaction, reaction or atmosphere within the brief. '
    'Do not pretend acoustic measurements identify choruses or unprovided lyrics. A selected action or '
    'other genre style shapes the relevant visual strand, not every shot in the MV. Intercut the supplied '
    'strands with motivated music-video edits; independent clips may change scene, framing or action phase '
    'without an establishing shot or matching the previous last pose. Keep identity and intended event '
    'progression, but do not demand a complete setup-development-payoff arc in every clip. Do not pad quiet '
    'moments with invented exposition. Preserve an immediate opening when requested. Let music contrasts '
    'support recurring supplied visual motifs and performance setups with variation; revisiting a location '
    'is not the same as replaying the story. '
    'shape expression, physical energy and camera choices without cutting on every transient. Balance '
    'visible singing and the other supplied content without fixed quotas; non-singing shots keep the '
    'soundtrack continuous. Do not literally illustrate every lyric or invent a final victory unless the '
    'user requests it. Use only the scene-change mechanisms and narrative ending allowed by the brief.'
)


POLICY = (
    'REFERENCE ROLE CONTRACT: Bind each user-designated character to the appropriate uploaded reference '
    'and preserve that mapping in subject_definitions. The main original reference identifies the primary '
    'performer; other images may be alternate views, other people, locations or objects as the user specifies. '
    'Multiple views of one person do not create extra people. Preserve all distinct people when a reference '
    'or brief intentionally includes a group; do not force every project into a single-person cast. '
    'Keep each identity distinct in face, hair, clothing and assigned role. An identity appearing in alternating '
    'scenes is one character, not simultaneous copies. Do not create a duplicate, double or matching opponent '
    'unless explicitly requested. Unreferenced supporting characters follow the brief and remain visually '
    'distinct from referenced characters; do not impose a fixed name or gender on every project. Preserve who sings, who does not sing, '
    'voice assignments and per-shot character counts. A song continuing over an action shot does not mean '
    'the action character is lip-syncing. Keep scene-specific props and behavior in their own scenes. '
    'Retain immediate openings, reserved endings and user exclusions. Character names and gender come '
    'only from the user or references, never from a fixed application persona.'
)


def reference_policy(picture_count, continuation=False):
    main = 2 if continuation else 1
    mapping = f'Main original reference: <Picture {main}>. '
    if continuation:
        mapping += '<Picture 1> is the previous final frame, not an additional character. '
    return mapping + f'Connected pictures: {picture_count}. ' + POLICY + '\n' + MV_POLICY


def enforce_reference_policy(text, policy):
    text = re.sub(r'\n*\[BANANA_REFERENCE_ROLES_V1\].*?\[/BANANA_REFERENCE_ROLES_V1\]',
                  '', text, flags=re.S).rstrip()
    return text + '\n\n[BANANA_REFERENCE_ROLES_V1]\n' + policy + '\n[/BANANA_REFERENCE_ROLES_V1]'


def ending_excerpt(brief):
    """Copy user-written ending text verbatim; never invent a destination scene."""
    lines = brief.splitlines()
    heading = re.compile(r'(?:【|\[|^\s*#+).*?(?:終局|結局|結尾|收尾|ending|finale|final shot)',re.I)
    section = []
    for i,line in enumerate(lines):
        if heading.search(line):
            section = [line]
            for following in lines[i+1:]:
                if re.search(r'【.+?】|^\s*#{1,6}\s',following):
                    break
                section.append(following)
            break
    if section:
        return '\n'.join(section).strip()[:5000]
    terminal = re.compile(r'最後|最終|收尾|結尾|結局|\b(?:final shot|last shot|end with|finish with|ending)\b',re.I)
    return '\n'.join(line for line in lines if terminal.search(line)
                     and not re.match(r'\s*(?:不要|禁止|勿|避免|不|never|do not|don.t)',line,re.I))[:5000]


def clip_scope(segment, brief, creative=False):
    count=segment.get('segment_count',1)
    index=segment.get('index',0)
    final=index==count-1
    spec=ending_excerpt(brief)
    text=(f'CURRENT CLIP ONLY: clip {index+1}/{count}, visible duration {segment["seconds"]:.6f}s. '
          'Write summary and every shot only for this source interval. Do not output the whole-song storyboard. '
          'Model alignment padding is not extra story time; all visible events must fit the requested duration. ')
    if final:
        if creative:
            text+=('FINAL SONG WINDOW: deliver the director treatment ending, using the user ending idea as a '
                   'creative anchor. Timing, staging and edit order may change; preserve explicitly locked '
                   'outcomes, reference roles and non-negotiable requirements. ')
        else:
            text+=('FINAL SONG WINDOW: preserve the user-required final event order AND terminal shot. '
               'A preceding gag, impact or victory is not the terminal shot if the user requires a later cut. '
               'No alternate ending, merged scene or substituted final location. ')
        if spec:
            text+=('\nUSER ENDING IDEA — VERBATIM CREATIVE REFERENCE:\n' if creative else
                   '\nUSER ENDING — VERBATIM, REQUIRED IN THIS FINAL WINDOW:\n')+spec
    else:
        text+=('NON-FINAL WINDOW: the whole-song ending is reserved, not a task for this clip. '
               'Do not stage the finale, deliver the final victory or label this clip as the end of the song. '
               'A local clip may stop in its current scene while the song/story continues; do not demand '
               'the whole-song terminal shot here. ')
        # Do not append the actual future finale to an early H3 generation prompt.
        # The complete user brief remains available to the rewriter/reviewer as reference.
    return text


def enforce_clip_scope(text, scope):
    text=re.sub(r'\n*\[BANANA_CLIP_SCOPE_V1\].*?\[/BANANA_CLIP_SCOPE_V1\]','',text,flags=re.S).rstrip()
    return text+'\n\n[BANANA_CLIP_SCOPE_V1]\n'+scope+'\n[/BANANA_CLIP_SCOPE_V1]'
