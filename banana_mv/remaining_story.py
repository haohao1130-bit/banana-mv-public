"""Edit only unfilmed Python-owned commissions after an acknowledged stop.

The original user screenplay, song windows, SRT and completed takes stay immutable.
Every accepted revision backs up all affected metadata before an atomic-file update.
"""
import copy
import hashlib
import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from banana_mv.scene_state import atomic_json, digest

_MARKER = re.compile(r"(?m)^=== CLIP ([1-9][0-9]*) \| ([0-9]+\.[0-9]{2})-([0-9]+\.[0-9]{2}) ===$")
_STOPPED = {"cancelled", "interrupted", "error"}
_MAX_TEXT = 300000
_MAX_CLIP = 20000
# Readers and updater share this lock so a GET cannot roll back a live commit.
_TRANSACTION_LOCK = threading.RLock()


def recover_pending(work):
    """Rollback a power-loss-interrupted metadata update before loading a job."""
    with _TRANSACTION_LOCK:
        directory = Path(work) / "story_revisions"
        if not directory.is_dir():
            return
        for manifest_path in sorted(directory.glob("*/manifest.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("status") != "backup_created":
                continue
            archive = manifest_path.parent
            for name in ("director_plan.json", "scene_state.json", "status.json"):
                original = archive / name
                if original.is_file():
                    target = Path(work) / name
                    restored = target.with_name(target.name + ".recover")
                    restored.write_bytes(original.read_bytes())
                    restored.replace(target)
            manifest["status"] = "rolled_back"
            manifest["recovered_at"] = time.time()
            atomic_json(manifest_path, manifest)


def _app():
    from banana_mv import server
    return server


def _prefix(job):
    """Return the first unfilmed index; reject timelines with holes."""
    if job.get("request", {}).get("director_schema") != 6:
        raise ValueError("剩餘通告單編輯只支援 5070 Python 通告單＋9B 導演模式。")
    if job.get("status") not in _STOPPED:
        raise ValueError("請先停爐，等目前的 H3 任務確實停止後再改劇情。")
    if job.get("continuation_restart") or job.get("continuation_generation"):
        raise ValueError("目前有未完成的接拍分支；請先確定正式採用的版本與接拍起點。")
    segments = job.get("segments") or []
    first = next((i for i, seg in enumerate(segments) if seg.get("status") != "done"), len(segments))
    if first == len(segments):
        raise ValueError("全部段落已拍攝完成，沒有剩餘通告單。")
    if any(seg.get("status") == "done" for seg in segments[first:]):
        raise ValueError("後面仍有已拍段落，請先處理接拍分支；不能覆蓋已完成影片。")
    if not all(isinstance(seg.get("director_plan"), dict) and
               seg["director_plan"].get("handoff_version") == 1 for seg in segments[first:]):
        raise ValueError("剩餘段落缺少 Python 拍攝通告單。")
    return first


def _header(seg):
    return "=== CLIP {} | {:.2f}-{:.2f} ===".format(
        seg["index"] + 1, seg["start"], seg["start"] + seg["seconds"])


def _revision(job, first):
    return digest({
        "id": job["id"], "first": first,
        "completed": [(s["index"], s.get("selected_take", "original"),
                       s.get("status")) for s in job["segments"][:first]],
        "pending": [(s["index"], s["director_plan"]["event"],
                     s["director_plan"].get("mode"), s.get("status"))
                    for s in job["segments"][first:]],
        "story_revision": job.get("remaining_story_revision"),
    })


def view(job_id):
    app = _app()
    job = app.read_state(job_id)
    first = _prefix(job)
    for seg in job["segments"][:first]:
        from banana_mv.takes import take_source
        if not app.valid_part(take_source(job, seg["index"]), seg, job["size"]):
            raise ValueError("已完成段落的採用影片不完整，暫停更新故事。")
    chunks = [_header(seg) + "\n" + seg["director_plan"]["event"].strip()
              for seg in job["segments"][first:]]
    return {
        "id": job_id, "from_index": first, "from_clip": first + 1,
        "locked_clips": first, "remaining": len(chunks),
        "revision": _revision(job, first),
        "text": "\n\n".join(chunks),
    }


def _parse(job, first, source):
    if not isinstance(source, str) or not source.strip() or len(source) > _MAX_TEXT:
        raise ValueError("剩餘通告單內容必須是文字，最多 30 萬字。")
    data = source.replace("\r\n", "\n").replace("\r", "\n").strip()
    matches = list(_MARKER.finditer(data))
    future = job["segments"][first:]
    if len(matches) != len(future) or not matches or data[:matches[0].start()].strip():
        raise ValueError("通告單段數或格式不符；請保留每個 === CLIP 編號與時間 === 標頭。")
    updates = {}
    for n, (match, seg) in enumerate(zip(matches, future)):
        if match.group(0) != _header(seg):
            raise ValueError("第 {} 段的段號或時間被改動；只能編輯標頭下面的劇情。".format(seg["index"] + 1))
        end = matches[n + 1].start() if n + 1 < len(matches) else len(data)
        event = data[match.end():end].strip()
        if not event or len(event) > _MAX_CLIP:
            raise ValueError("第 {} 段內容不可空白，每段最多 2 萬字。".format(seg["index"] + 1))
        updates[seg["index"]] = event
    return updates


def preview(job_id, revision, source):
    app = _app()
    job = app.read_state(job_id)
    first = _prefix(job)
    if revision != _revision(job, first):
        raise ValueError("作品狀態已更新，請重新開啟剩餘通告單，避免覆蓋新進度。")
    changed = [i + 1 for i, event in _parse(job, first, source).items()
               if event != job["segments"][i]["director_plan"]["event"].strip()]
    return {"from_clip": first + 1, "changed_clips": changed,
            "remaining": len(job["segments"]) - first,
            "message": "變動第 {} 段；從第 {} 段重新接拍。".format(
                "、".join(map(str, changed)) or "無", first + 1)}


def _allowed_operations(event):
    # Only narrative operations hinted by edited text are authorized.
    actions = ["update", "move", "use"]
    checks = {
        "remove": r"脫|摘|卸|移除|扯掉|取下|remove|take off",
        "dress": r"穿上|戴上|重新穿|重新戴|dress|put on",
        "acquire": r"拿起|接過|拾起|獲得|取得|pick up|grab|acquire",
        "drop": r"放下|丟下|扔掉|掉落|drop|place down",
        "damage": r"打碎|破壞|受傷|撞壞|碎裂|damage|break",
        "restore": r"修復|恢復|復原|restore|repair",
        "heal": r"治癒|療傷|痊癒|heal",
    }
    for operation, pattern in checks.items():
        if re.search(pattern, event, re.I):
            actions.append(operation)
    return actions


def _update_ledger(ledger, job, first, revision_id):
    """Preserve committed state/checksums; replace only unused future event IDs."""
    ledger = copy.deepcopy(ledger)
    commits = ledger.get("commits", [])
    if len(commits) != first:
        raise ValueError("跨段狀態提交數與已完成影片不一致，停止更新以保護舊作品。")
    old = ledger["event_catalog"]
    referenced = {eid for commit in commits for eid in (
        commit.get("planned_events", []) + commit.get("completed_events", []))}
    # Keep event prerequisites required by the committed prefix.
    queue = list(referenced)
    while queue:
        event = old.get(queue.pop())
        if not event:
            raise ValueError("已完成的事件狀態缺少事件定義。")
        for dep in event.get("depends_on", []):
            if dep not in referenced:
                referenced.add(dep)
                queue.append(dep)
    catalog = {key: copy.deepcopy(value) for key, value in old.items() if key in referenced}
    # New events are assigned to the remaining fixed source windows only.
    for seg in job["segments"][first:]:
        event = seg["director_plan"]["event"]
        eid = "REV{}_C{}".format(revision_id[:8], seg["index"])
        catalog[eid] = {
            "event_id": eid,
            "description": event[:1800],
            "repeatable": False, "reserved_final": False,
            "depends_on": [], "allowed_operations": _allowed_operations(event),
        }
    ledger["event_catalog"] = catalog
    ledger["events_sha256"] = digest(catalog)
    ledger["remaining_story_revision"] = revision_id
    return ledger


def _update(job_id, revision, source):
    app = _app()
    if not app.GPU_LOCK.acquire(blocking=False):
        raise ValueError("GPU 工作尚未停止，不能更新後續故事。")
    try:
        from banana_mv import takes
        cfg = app.backend.load_config()
        job = app.read_state(job_id)
        takes.require_idle(job, cfg)
        first = _prefix(job)
        if not isinstance(revision, str) or revision != _revision(job, first):
            raise ValueError("作品已更新，請重新載入通告單後再提交。")
        for seg in job["segments"][:first]:
            if not app.valid_part(takes.take_source(job, seg["index"]), seg, job["size"]):
                raise ValueError("已完成丹藥缺少有效檔案，停止修改。")
        updates = _parse(job, first, source)
        changed = [i for i, value in updates.items()
                   if job["segments"][i]["director_plan"]["event"].strip() != value]
        if not changed:
            raise ValueError("剩餘通告單沒有修改，不需要更新。")
        work = app.job_dir(job_id)
        plan_path = work / "director_plan.json"
        state_path = work / "status.json"
        ledger_path = work / "scene_state.json"
        if not plan_path.is_file():
            raise ValueError("Python 原始通告單檔案遺失。")
        old_plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if old_plan.get("version") != 6 or len(old_plan.get("segments", [])) != len(job["segments"]):
            raise ValueError("不是可更新的 Python 通告單版本。")
        new_job = copy.deepcopy(job)
        for seg in new_job["segments"][first:]:
            i = seg["index"]
            seg["director_plan"]["event"] = updates[i]
            seg["status"] = "waiting"
            seg["refresh_prompt"] = True
            for field in ("prompt", "prompt_id", "prompt_rewrite", "scene_state_debug",
                          "scene_state_attempt", "scene_state_prompt_sha256",
                          "scene_state_rewrite_debug", "interrupted_render", "prompt_profile"):
                seg.pop(field, None)
            if i:
                seg["previous_planned_event"] = new_job["segments"][i - 1]["director_plan"]["event"]
        new_plan = copy.deepcopy(old_plan)
        for seg in new_job["segments"][first:]:
            new_plan["segments"][seg["index"]]["event"] = seg["director_plan"]["event"]
        revision_id = uuid.uuid4().hex
        new_plan["remaining_story_revision"] = revision_id
        new_plan["content_sha256"] = digest({key: value for key, value in new_plan.items()
                                              if key not in ("input_sha256", "content_sha256")})
        new_job["remaining_story_revision"] = revision_id
        new_job["remaining_story_updated_at"] = time.time()
        new_job["remaining_story_from"] = first
        new_job["remaining_story_changed"] = [i + 1 for i in changed]
        new_job["status"] = "interrupted"
        new_job["stop_reason"] = "story_edited"
        new_job.pop("rewrite_attempt", None)
        new_job.pop("error", None)
        new_job.pop("error_stage", None)
        new_ledger = None
        if job["request"].get("scene_state_version") == 1:
            if not ledger_path.is_file():
                raise ValueError("跨段事件狀態遺失，不能安全改寫後段。")
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            new_ledger = _update_ledger(ledger, new_job, first, revision_id)
        if new_job.get("plan_approved"):
            # Approval must follow exactly the revised authoritative plan.
            # plan_revision reads disk; calculate after the plan is committed.
            new_job["plan_approved"] = None
        # Save rollback copies before mutating any active metadata.
        archive = work / "story_revisions" / revision_id
        archive.mkdir(parents=True, exist_ok=False)
        originals = {path: path.read_bytes() for path in
                     (plan_path, state_path, ledger_path) if path.is_file()}
        for path, contents in originals.items():
            (archive / path.name).write_bytes(contents)
        atomic_json(archive / "manifest.json", {
            "revision": revision_id, "from_clip": first + 1,
            "changed_clips": [i + 1 for i in changed], "created": time.time(),
            "status": "backup_created",
        })
        try:
            atomic_json(plan_path, new_plan)
            if new_ledger is not None:
                atomic_json(ledger_path, new_ledger)
            if job.get("plan_approved"):
                new_job["plan_approved"] = app.plan_revision(new_job)
            app.write_state(new_job)
            atomic_json(archive / "manifest.json", {
                "revision": revision_id, "from_clip": first + 1,
                "changed_clips": [i + 1 for i in changed], "status": "applied",
            })
        except Exception:
            for path, contents in originals.items():
                temp = path.with_name(path.name + ".story_restore_" + revision_id[:8])
                temp.write_bytes(contents)
                temp.replace(path)
            raise
        return {"ok": True, "from_clip": first + 1,
                "changed_clips": [i + 1 for i in changed],
                "remaining": len(new_job["segments"]) - first,
                "message": "新通告單已更新，請按「續跑未完成段落」，從第 {} 段開始。".format(first + 1)}
    finally:
        app.GPU_LOCK.release()


def update(job_id, revision, source):
    with _TRANSACTION_LOCK:
        return _update(job_id, revision, source)
