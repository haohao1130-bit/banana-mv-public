"""SRT 歌手角色與參考圖的對應（S1 → <Picture N>）。

原本這裡還有一整套「退稿檢查」：海邊／公寓換裝、白色綁帶比基尼、短袖短褲、
SRT 以外不准 rap 等，都是為特定一支 MV 臨時寫死的規則，換別的故事只會誤判並觸發
反覆重寫。已移除；換裝改用 continuity.py 的通用換裝點，入鏡檢查也在 continuity.py。
"""
import re


_ROLE_BIND = re.compile(r'(?im)^\s*(S[1-8])\s*[=:：＝]\s*(<Picture \d+>)')
# Existing one-click MV briefs normally declare <Picture 1>＝角色，S1 instead.
# Treat either orientation as an explicit identity bind; never infer from image order.
_IMAGE_ROLE_BIND = re.compile(
    r'(?im)^\s*(?:(<Picture\s+\d+>)|@(?:圖片|图片|image)\s*(\d+))'
    r'\s*[=:：＝]\s*[^\n]*?\b(S[1-8])\b'
)
# Long-form director briefs define image, character, and SRT role on separate
# lines: Subject 1｜name / Use @圖片1 / [S1] = Subject 1.
_SUBJECT_HEADING = re.compile(
    r'(?im)^\s*(?:<Subject\s+(\d+)>|Subject\s+(\d+))\s*[｜|:：]\s*\S'
)
_ROLE_SUBJECT = re.compile(
    r'(?im)^\s*\[\s*(S[1-8])\s*\]\s*[=:：＝]\s*(?:<Subject\s+(\d+)>|Subject\s+(\d+))(?!\w)'
)
_PICTURE_USE = re.compile(
    r'(?i)^\s*(?:Use|使用)\s+(?:<Picture\s+(\d+)>|@(?:圖片|图片|image)\s*(\d+))(?=\s|$)'
)
_ENGLISH_DIRECTOR_SECTION = re.compile(
    r'^\s*(?:0[1-9]|10)\s*[｜|]\s*[A-Z]', re.I
)
def role_pictures(fixed_setup):
    """Resolve explicit SRT-to-image links, including multi-line director briefs.

    A Subject heading is not a singer identity by itself. Only a user-written
    role-to-subject or role-to-picture rule can connect it to a vocal role.
    Never guess from picture order, gender, or the soundtrack.
    """
    roles = {role.upper(): picture for role, picture in _ROLE_BIND.findall(fixed_setup)}
    for picture, index, role in _IMAGE_ROLE_BIND.findall(fixed_setup):
        roles.setdefault(role.upper(), picture or f'<Picture {index}>')
    subject_pictures = {}
    current = None
    for line in fixed_setup.splitlines():
        if _ENGLISH_DIRECTOR_SECTION.match(line):
            current = None
        subject = _SUBJECT_HEADING.match(line)
        if subject:
            index = subject[1] or subject[2]
            current = index
            continue
        if current:
            picture = _PICTURE_USE.match(line)
            if picture:
                subject_pictures.setdefault(current, f'<Picture {picture[1] or picture[2]}>')
    for role, numbered, bracketed in _ROLE_SUBJECT.findall(fixed_setup):
        ref = subject_pictures.get(numbered or bracketed)
        if ref:
            roles.setdefault(role.upper(), ref)
    return roles


def scene_wardrobe_schedule(event, fixed_setup, pictures, seconds):
    """相容舊介面：原本的海邊→公寓換裝時間軸已移除，一律沒有排程。"""
    return []
