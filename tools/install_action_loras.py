"""下載動作 LoRA 控制台新增的兩顆 V2（Fight Flow V2、Motion Repair V2）。

已存在且 SHA-256 相符就跳過；下載到 .part，驗證通過才改名，不覆蓋原版 Motion_Repair 或 Combat V2。
用法（5070 本機）：python tools\\install_action_loras.py --dest F:\\AI\\Models\\loras
"""
import argparse
import hashlib
import sys
import time
import urllib.request
from pathlib import Path

FILES = {
    'H3_Fight_Flow_V2.safetensors': (
        'https://huggingface.co/JOKER141/H3-Fight-Flow-Fight-Interaction-LoRA/resolve/main/H3_Fight_Flow_V2.safetensors',
        'ee3af45c4ec4efb2460a20f08b122a2a8dabc2a8d317d257ac3623795477c608'),
    'Motion_Repair_V2.safetensors': (
        'https://huggingface.co/JOKER141/MiniMax-H3-General-Motion-Continuity-Repair/resolve/main/Motion_Repair_V2.safetensors',
        'edfa0e2858caeba7be9108883f61da8525d3c58af998c94ac7a449d9603d7574'),
}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def fetch(url, target, tries=3):
    part = target.with_name(target.name + '.part')
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as response, open(part, 'wb') as out:
                while block := response.read(1 << 20):
                    out.write(block)
            return part
        except OSError as error:
            print(f'  下載中斷（第 {attempt} 次）：{error}')
            part.unlink(missing_ok=True)
            time.sleep(3 * attempt)
    raise SystemExit(f'下載失敗：{target.name}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dest', default=r'F:\AI\Models\loras', help='ComfyUI 的 loras 資料夾')
    dest = Path(parser.parse_args().dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in FILES.items():
        target = dest / name
        if target.exists():
            if sha256(target) == expected:
                print(f'已存在且校驗相符，跳過：{target}')
                continue
            raise SystemExit(f'{target} 已存在但 SHA-256 不符；請確認後自行刪除再重跑，不會自動覆蓋。')
        print(f'下載 {name} …')
        part = fetch(url, target)
        actual = sha256(part)
        if actual != expected:
            part.unlink(missing_ok=True)
            raise SystemExit(f'{name} SHA-256 不符（{actual}），已刪除暫存檔。')
        part.replace(target)
        print(f'完成：{target}')
    print('全部就緒，請重啟 ComfyUI。')


if __name__ == '__main__':
    sys.exit(main())
