"""BananaMV 的共同設定組合：常用角色圖＋綁定文字存起來，新開一桌一鍵載入。

組合只記素材庫裡的圖片編號與文字，圖片本身留在素材庫（library），不另外複製。
"""
import json
import threading
import time
import uuid

from banana_mv import services

SLOTS = 9
MAX_PRESETS = 60
_lock = threading.Lock()


def _path():
    return services.DATA / 'mv_presets.json'


def _read():
    path = _path()
    if not path.is_file():
        return []
    try:
        rows = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return rows if isinstance(rows, list) else []


def _write(rows):
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def image_asset(asset_id):
    """素材庫裡的一張圖（只讀，不需要 ComfyUI）。"""
    item = next((row for row in services.library_index() if row.get('id') == asset_id), None)
    if item is None or item.get('kind') != 'image':
        raise ValueError('找不到這張參考圖，可能已從素材庫刪除。')
    return item, services.safe_child(services.LIBRARY, item['file'])


def list_presets():
    """回傳組合清單；素材庫裡已不存在的圖片標成 missing，讓前端提示。"""
    known = {row.get('id') for row in services.library_index() if row.get('kind') == 'image'}
    result = []
    for row in _read():
        slots = row.get('slots', [None] * SLOTS)
        result.append(dict(row, missing=[i + 1 for i, aid in enumerate(slots) if aid and aid not in known]))
    return sorted(result, key=lambda row: -row.get('updated', 0))


def save_preset(body):
    name = body.get('name')
    shared = body.get('shared', '')
    slots = body.get('slots')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
        raise ValueError('組合名稱需要 1–40 字。')
    if not isinstance(shared, str) or len(shared) > 12000:
        raise ValueError('共同設定最多 12000 字。')
    if not isinstance(slots, list) or len(slots) != SLOTS:
        raise ValueError(f'參考圖需為 {SLOTS} 格。')
    for index, aid in enumerate(slots, 1):
        if aid is not None:
            if not isinstance(aid, str):
                raise ValueError(f'圖片{index} 的編號無效。')
            image_asset(aid)
    if not shared.strip() and not any(slots):
        raise ValueError('共同設定是空的，沒有東西可以存。')
    name = name.strip()
    with _lock:
        rows = _read()
        existing = next((row for row in rows if row.get('name') == name), None)
        if existing is None and len(rows) >= MAX_PRESETS:
            raise ValueError(f'最多存 {MAX_PRESETS} 組，請先刪掉不用的組合。')
        row = existing or {'id': uuid.uuid4().hex[:10], 'name': name, 'created': time.time()}
        row.update(shared=shared, slots=slots, updated=time.time())
        if existing is None:
            rows.append(row)
        _write(rows)
    return list_presets()


def delete_preset(body):
    preset_id = body.get('id')
    with _lock:
        rows = _read()
        kept = [row for row in rows if row.get('id') != preset_id]
        if len(kept) == len(rows):
            raise ValueError('找不到這個組合。')
        _write(kept)
    return list_presets()
