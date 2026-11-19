"""Carry explicitly authored anatomy as a stable per-role body_form state.

This module reads *fixed reference facts*, never searches the plot or judges
9B's cinematography. No assumption that an unmentioned actor is humanoid.
"""
import re


_ROLE_SECTION = re.compile(
    r'^\s*(?:[■#*]+\s*)?(?:S([12])|<Subject\s+([12])>|Subject\s+([12]))'
    r'(?=\s|[｜|：:(（])',
    re.I,
)
_ROLE_FORM = re.compile(
    r'^\s*S([12])\s+(?:body[_ -]?form|anatomy|morphology|身體形態|身體結構|固定形態)'
    r'\s*[：:=]\s*(.+)$',
    re.I,
)
_FORM = re.compile(r'^(?:body[_ -]?form|anatomy|morphology|身體形態|身體結構|固定形態)\s*[：:=]\s*(.+)$', re.I)
_FORM_HEADING = ('形態固定', '固定形態', '身體形態', '身體結構',
                 'body_form', 'body form', 'morphology', 'anatomy')


def declared_body_forms(fixed_setup):
    """Extract user-supplied morphology; keep role keys independent of Picture offsets.

    Supports explicit S1/S2 BODY FORM fields and V6-style
    '■ S2 白素貞（形態固定，全片一致）' followed by its anatomical paragraph.
    The associated description is copied, never re-authored or deduced from
    events, wardrobe, an image, or 9B shot prose.
    """
    forms = {}
    current = None
    expect_description = False
    for raw in fixed_setup.splitlines():
        line = raw.strip()
        if not line:
            continue
        explicit_role = _ROLE_FORM.match(line)
        if explicit_role:
            forms['S' + explicit_role[1]] = explicit_role[2].strip()
            expect_description = False
            continue

        heading = _ROLE_SECTION.match(line)
        if heading:
            current = 'S' + next(value for value in heading.groups() if value)
            lowered = line.lower()
            expect_description = any(label in lowered for label in _FORM_HEADING)
            continue

        if line.startswith(('■', '【', '#')) or re.match(r'^\s*ACT\s+\d+', line, re.I):
            current = None
            expect_description = False
            continue

        explicit = _FORM.match(line)
        if explicit and current:
            forms[current] = explicit[1].strip()
            expect_description = False
            continue

        if current and expect_description and not line.startswith(('・', '-', '*')):
            forms[current] = line
            expect_description = False

    return forms
