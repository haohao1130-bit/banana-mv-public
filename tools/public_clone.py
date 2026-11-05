"""Anonymous public-repository bootstrap; embedded in the Colab notebook."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def clone_project(project, repo_url):
    project = Path(project)
    if project.exists():
        if not (project/'tools/colab_runtime.py').is_file():
            raise RuntimeError('程式目錄不完整，請使用新的執行階段重新執行①。')
        print('沿用此執行階段已有的公開版程式。更新請使用新的執行階段。')
        return
    project.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='banana-public-',dir=project.parent) as scratch:
        checkout = Path(scratch)/'checkout'
        result = subprocess.run(
            ['git','-c','credential.helper=','clone','--depth','1',repo_url,str(checkout)],
            env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_ASKPASS='/bin/false'),
            capture_output=True,text=True)
        if result.returncode:
            raise RuntimeError('公開版下載失敗，請確認倉庫已公開且網路正常；不需要 GitHub Token。')
        shutil.move(str(checkout),str(project))
    print('✅ 已載入 Banana MV 公開版。')
