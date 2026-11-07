"""Immutable complete-MV versions; final.mp4 remains the current project master."""
import hashlib
from pathlib import Path
import re
import shutil
import time
import uuid


def archive(job,work,source,reason,choices=None):
    work,source=Path(work),Path(source)
    existing=[int(m[1]) for p in work.glob('final_v*.mp4')
              if (m:=re.fullmatch(r'final_v(\d+)\.mp4',p.name))]
    version=max(existing+[0])+1
    target=work/f'final_v{version:03d}.mp4'
    temp=work/f'.master_{uuid.uuid4().hex}.tmp'
    try:
        shutil.copyfile(source,temp)
        if target.exists():raise ValueError('成片版本已存在，不能覆寫。')
        temp.replace(target)
    finally:temp.unlink(missing_ok=True)
    digest=hashlib.sha256()
    with target.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    row={'version':version,'file':target.name,'created':time.time(),'reason':reason,
         'sha256':digest.hexdigest(),'takes':{str(i):(choices or {}).get(i,s.get('selected_take','original'))
                                             for i,s in enumerate(job['segments'])}}
    job.setdefault('final_versions',[]).append(row)
    return row


def preserve_current(job,work):
    """Migrate an existing unversioned master before any replacement."""
    work=Path(work)
    if not (work/'final.mp4').is_file():return
    if any(r['version']==job.get('current_master') and (work/r['file']).is_file()
           for r in job.get('final_versions',[])):return
    row=archive(job,work,work/'final.mp4','original')
    job['current_master']=row['version']


def source(job,work,version=None):
    if version is None:return Path(work)/'final.mp4'
    if isinstance(version,bool) or not str(version).isdigit() or int(version)<1:
        raise ValueError('無效的成片版本。')
    number=int(version)
    if not any(r.get('version')==number for r in job.get('final_versions',[])):
        raise ValueError('找不到此成片版本。')
    path=Path(work)/f'final_v{number:03d}.mp4'
    if not path.is_file():raise ValueError('此成片版本檔案遺失。')
    return path
