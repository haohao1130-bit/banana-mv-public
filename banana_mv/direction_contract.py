"""Small deterministic reference and ending-scope checks."""
import re

_TERMINAL = re.compile(r'最後(?:畫面|一鏡|鏡頭)|最終(?:畫面|鏡頭)|結尾(?:畫面|鏡頭)|\b(?:final image|final shot|last shot|terminal shot|closing image)\b', re.I)


def scoped_constraints(constraints, final):
    """Legacy string constraints are split at sentences, preserving role clauses."""
    clauses = [part.strip() for text in constraints
               for part in re.split(r'(?<=[.!?。！？;；])\s*', text) if part.strip()]
    return [text for text in clauses if final or not _TERMINAL.search(text)]


def validate_subject_bindings(text, appearance):
    """Check explicit actor declarations only; never infer roles from prose."""
    definitions=text.split('summary:',1)[0] if 'subject_definitions:' in text else ''
    for sid,picture in re.findall(r'^\s*<Subject (\d+)>[^\n]*?<Picture (\d+)>',definitions,re.M):
        expected=appearance['characters'].get('S'+sid,{}).get('connected_reference')
        if expected and expected!=f'<Picture {picture}>':
            raise ValueError(f'<Subject {sid}> 必須綁定 {expected}，不可改為 <Picture {picture}>。')


H3_SECTIONS=('subject_definitions','summary','retention_analysis','detailed_description',
             'overall_soundscape','non_diegetic_music')


def validate_h3_sections(text):
    """Check the native six-field contract, without interpreting the story."""
    headers=list(re.finditer(r'^\s*('+'|'.join(H3_SECTIONS)+r')\s*:',text,re.M))
    if tuple(match[1] for match in headers)!=H3_SECTIONS:
        raise ValueError('Ref2VA 需依序包含六個區塊：'+', '.join(H3_SECTIONS))
    for i,match in enumerate(headers):
        end=headers[i+1].start() if i+1<len(headers) else len(text)
        if not text[match.end():end].strip():
            raise ValueError('Ref2VA 區塊不可空白：'+match[1])
