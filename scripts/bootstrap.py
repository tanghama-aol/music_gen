#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本 skill 附带的配乐生成管线部署到目标工作区，并检查运行环境。

用法（在 skill 的 scripts/ 目录之外执行时给绝对路径）：
    python bootstrap.py --target C:/path/to/workspace
    python bootstrap.py --target C:/path/to/workspace --force
    python bootstrap.py --check-only
    python bootstrap.py --sync-from /path/to/live/music

默认部署到 <target>/music/，因为管线脚本都用 Path(__file__).parent 定位自身，
必须放在同一层目录里才能互相 import。产物会写到：
    <target>/music/game/public/assets/manifest.json
    <target>/music/game/public/assets/music/*_calm.ogg / *_fight.ogg
    <target>/music/tmp/                         # 模型原始 mp3 与中间 wav 缓存

已存在的同名脚本默认保留（避免覆盖用户改过的 STYLES / 提示词），
需要覆盖时加 --force。
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# 会被部署的管线脚本；不要包含 bootstrap.py 自身。
PIPELINE = [
    "gen_music_api.py",
    "gen_music_space.py",
    "gen_music_segments.py",
    "fix_levels.py",
    "verify_music.py",
    "space_client.py",
    "gen_vocal_test.py",
    "verify_vocal_test.py",
]


def check_env() -> bool:
    ok = True
    print("== 运行环境 ==")
    v = sys.version_info
    good = v >= (3, 10)
    print(f"  Python {v.major}.{v.minor}.{v.micro}  {'OK' if good else '需要 >= 3.10'}")
    ok &= good
    for mod in ("numpy", "scipy"):
        found = importlib.util.find_spec(mod) is not None
        print(f"  {mod:<10}   {'OK' if found else '缺失：pip install ' + mod}")
        ok &= found
    for exe in ("ffmpeg", "ffprobe"):
        path = shutil.which(exe)
        print(f"  {exe:<10}   {'OK ' + path if path else '缺失：需加入 PATH'}")
        ok &= path is not None
    if shutil.which("ffmpeg"):
        try:
            r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                               capture_output=True, text=True, check=True)
            has = "libvorbis" in r.stdout
            print(f"  libvorbis    {'OK' if has else '缺失：ffmpeg 需带 libvorbis 编码器'}")
            ok &= has
        except Exception as e:
            print(f"  libvorbis    无法检测：{e}")
            ok = False
    print(f"  结论：{'全部就绪' if ok else '有缺项，先补齐再生成'}")
    return bool(ok)


def deploy(target: Path, force: bool) -> None:
    dest = target / "music"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "tmp").mkdir(exist_ok=True)
    assets = dest / "game" / "public" / "assets" / "music"
    assets.mkdir(parents=True, exist_ok=True)
    print(f"== 部署到 {dest} ==")
    for name in PIPELINE:
        src, dst = HERE / name, dest / name
        if not src.exists():
            print(f"  ! 缺少 {name}，跳过")
            continue
        if dst.exists() and not force:
            print(f"  = 保留 {name}（已存在；--force 可覆盖）")
            continue
        shutil.copy2(src, dst)
        print(f"  + 写入 {name}")
    print(f"  产物目录：{assets}")
    print(f"  清单路径：{assets.parent / 'manifest.json'}")
    print("\n下一步：")
    print(f"  cd {dest}")
    print("  python -u gen_music_segments.py --all --skip-existing "
          "--duration 40 --segments 2 --steps 4")
    print("  python fix_levels.py && python verify_music.py")


def sync_from(src_dir: Path) -> None:
    """维护用：把某条已调通的实跑管线同步回 skill 的 scripts/。"""
    print(f"== 从 {src_dir} 同步脚本回 skill ==")
    for name in PIPELINE:
        s = src_dir / name
        if not s.exists():
            print(f"  ! 源缺少 {name}，跳过")
            continue
        shutil.copy2(s, HERE / name)
        print(f"  + 更新 {name}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", type=Path, default=Path.cwd(),
                    help="目标工作区根目录（默认当前目录），脚本会放在 <target>/music/")
    ap.add_argument("--force", action="store_true", help="覆盖目标目录中已有的同名脚本")
    ap.add_argument("--check-only", action="store_true", help="只检查依赖，不部署脚本")
    ap.add_argument("--sync-from", type=Path,
                    help="维护用：从实跑管线目录反向同步脚本到 skill")
    args = ap.parse_args()

    if args.sync_from:
        sync_from(args.sync_from.resolve())
        return 0
    ok = check_env()
    if not args.check_only:
        deploy(args.target.resolve(), args.force)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
