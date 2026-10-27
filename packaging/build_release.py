#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""生成一次发布的全套产物（完整包 / 增量包 / 清单 / latest.json）。

用法：
  # 基线版（第一次，没有上一版）
  python packaging/build_release.py --bootstrap ^
      --stage "E:\一键lora\review_fix_v25\stage" ^
      --base  "E:\一键lora\output\一键LoRA_最新完整包_20261023_182135.zip"

  # 日常发版
  python packaging/build_release.py ^
      --stage "E:\一键lora\review_fix_v25\stage" ^
      --base  "E:\一键lora\output\一键LoRA_最新完整包_20261023_182135.zip" ^
      --notes "修复 WD14 在部分环境下的报错"

产物写到 E:\一键lora\output\release\<版本>\，同时刷新仓库里的
updates/manifests/<版本>.json 和 updates/latest.json。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
UPDATES = REPO / "updates"
MANIFESTS = UPDATES / "manifests"
sys.path.insert(0, str(HERE))
import make_security  # noqa: E402

# 不进包 / 不参与更新的路径（用户数据、运行时状态）
EXCLUDE_DIRS = ("__pycache__",)
EXCLUDE_PARTS = (".pyc", ".pyo", ".tmp", ".part", ".log")
EXCLUDE_PREFIXES = (
    "app/task_data/",
    "app/output/",
    "app/training_env/",
    "app/models/",
    "app/logs/",
    "app/update/staging/",
    "app/update/download/",
    "app/update/backup_",
)
EXCLUDE_FILES = {
    "app/configs/env.json",
    "app/configs/model_catalog.json",
    "app/update/installed.json",
    "app/update/staged.json",
    "app/update/journal.json",
    "app/update/update.log",
    "app/version.json",
    "SHA256SUMS.json",
}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text("utf-8-sig"))
    except (OSError, ValueError):
        return default


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), "utf-8")


def version_key(v: str) -> tuple:
    core = v.lstrip("vV").split("-")[0]
    return tuple(int(x) for x in core.split(".") if x.isdigit())


def excluded(rel: str) -> bool:
    if rel in EXCLUDE_FILES:
        return True
    if any(rel.startswith(p) for p in EXCLUDE_PREFIXES):
        return True
    parts = rel.split("/")
    if any(p in EXCLUDE_DIRS for p in parts):
        return True
    return rel.endswith(EXCLUDE_PARTS)


def load_base(path: Path) -> dict:
    tree = {}
    with zipfile.ZipFile(path) as z:
        prefix = "LoRA_Trainer/"
        names = [n for n in z.namelist() if n.startswith(prefix) and not n.endswith("/")]
        sums_name = prefix + "SHA256SUMS.json"
        if sums_name in names:
            sums = json.loads(z.read(sums_name).decode("utf-8-sig"))
            for rel, expect in sums.items():
                got = sha(z.read(prefix + rel))
                if got != expect:
                    raise SystemExit("基线包校验失败：%s" % rel)
        for name in names:
            rel = name[len(prefix):]
            if rel == "SHA256SUMS.json":
                continue
            tree[rel] = z.read(name)
    return tree


def load_stage(stage: Path) -> dict:
    tree = {}
    for sub in ("app", "tokenizers"):
        root = stage / sub
        if not root.is_dir():
            raise SystemExit("stage 缺少目录：%s" % root)
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(stage).as_posix()
            if excluded(rel):
                continue
            tree[rel] = p.read_bytes()
    exe = stage / "一键Lora.exe"
    if exe.is_file():
        tree["一键Lora.exe"] = exe.read_bytes()
    return tree


def build(base: dict, stage: dict, version: str, cfg: dict, notes: str,
          prev: dict | None, out_dir: Path) -> dict:
    tree = dict(base)
    tree.update(stage)
    tree = {k: v for k, v in tree.items() if not excluded(k)}

    tree["app/version.json"] = json.dumps({
        "schema": 1,
        "version": version,
        "channel": cfg.get("channel", "stable"),
        "repo": cfg["repo"],
        "released": time.strftime("%Y-%m-%d"),
    }, ensure_ascii=False, indent=2).encode()

    tree["app/tools/security.py"] = make_security.seal(tree)
    make_security.verify_seal(tree)

    files = {rel: sha(b) for rel, b in tree.items()}
    installed = {"schema": 1, "version": version, "files": files}
    installed_bytes = json.dumps(installed, ensure_ascii=False).encode()
    tree["app/update/installed.json"] = installed_bytes
    files["app/update/installed.json"] = sha(installed_bytes)
    sums_bytes = json.dumps(files, ensure_ascii=False, indent=2).encode()
    tree["SHA256SUMS.json"] = sums_bytes
    manifest = dict(files)
    manifest["SHA256SUMS.json"] = sha(sums_bytes)

    prev_files = (prev or {}).get("files") or {}
    changed = sorted(rel for rel, h in manifest.items() if prev_files.get(rel) != h)
    full_only = any(rel == "一键Lora.exe" or rel.startswith(("python/", "Mock")) for rel in changed)

    out_dir.mkdir(parents=True, exist_ok=True)
    full_name = "YijianLoRA-full-v%s.zip" % version
    full_path = out_dir / full_name
    with zipfile.ZipFile(full_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
        for rel in sorted(tree):
            z.writestr("LoRA_Trainer/" + rel, tree[rel])

    manifest_obj = {"schema": 1, "version": version, "files": manifest}
    manifest_name = "YijianLoRA-manifest-v%s.json" % version
    manifest_path = out_dir / manifest_name
    manifest_bytes = json.dumps(manifest_obj, ensure_ascii=False, indent=2).encode()
    manifest_path.write_bytes(manifest_bytes)

    pack_path = None
    pack_info = None
    if prev is not None and changed:
        pack_name = "YijianLoRA-pack-v%s.zip" % version
        pack_path = out_dir / pack_name
        with zipfile.ZipFile(pack_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            for rel in changed:
                z.writestr(rel, tree[rel])
        pack_info = {
            "url": "https://github.com/%s/releases/download/v%s/%s" % (cfg["repo"], version, pack_name),
            "sha256": sha(pack_path.read_bytes()),
            "size": pack_path.stat().st_size,
        }

    history = list((prev or {}).get("_history") or [])
    if not history:
        history = [{"version": version, "pack": None}]
    else:
        history.append({"version": version, "from": prev["version"], "pack": pack_info})

    latest = {
        "schema": 1,
        "version": version,
        "tag": "v" + version,
        "released": time.strftime("%Y-%m-%d"),
        "channel": cfg.get("channel", "stable"),
        "notes": notes,
        "full_only": bool(full_only),
        "full": {
            "url": "https://github.com/%s/releases/download/v%s/%s" % (cfg["repo"], version, full_name),
            "sha256": sha(full_path.read_bytes()),
            "size": full_path.stat().st_size,
        },
        "manifest": {
            "url": "https://github.com/%s/releases/download/v%s/%s" % (cfg["repo"], version, manifest_name),
            "sha256": sha(manifest_bytes),
            "size": len(manifest_bytes),
        },
        "history": history,
    }
    (out_dir / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2), "utf-8")

    # ---- 校验产物 ----
    with zipfile.ZipFile(full_path) as z:
        got = {n[len("LoRA_Trainer/"):] for n in z.namelist() if not n.endswith("/")}
        if got != set(tree):
            raise SystemExit("完整包文件集合不一致")
        for rel, h in manifest.items():
            if rel == "SHA256SUMS.json":
                continue
            if sha(z.read("LoRA_Trainer/" + rel)) != h:
                raise SystemExit("完整包校验失败：%s" % rel)
    if pack_path is not None:
        with zipfile.ZipFile(pack_path) as z:
            if set(z.namelist()) != set(changed):
                raise SystemExit("增量包文件集合不一致")
            for rel in changed:
                if sha(z.read(rel)) != manifest[rel]:
                    raise SystemExit("增量包校验失败：%s" % rel)

    write_json(MANIFESTS / ("%s.json" % version), manifest_obj)
    write_json(UPDATES / "latest.json", latest)
    return {"version": version, "tree": len(tree), "changed": len(changed),
            "full": str(full_path), "pack": str(pack_path) if pack_path else None,
            "pack_bytes": pack_info["size"] if pack_info else 0,
            "full_only": full_only, "latest": str(out_dir / "latest.json"),
            "latest_obj": latest, "manifest": str(manifest_path)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--version", default=None)
    ap.add_argument("--notes", default="")
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cfg = read_json(HERE / "release.json", {})
    version = args.version or str(cfg.get("version") or "")
    if not version:
        raise SystemExit("release.json 缺少 version")
    if not cfg.get("repo") or "OWNER" in cfg["repo"] or "/" not in cfg["repo"]:
        raise SystemExit("release.json 里的 repo 还没填（格式：用户名/仓库名）")

    existing = sorted((p.stem for p in MANIFESTS.glob("*.json")), key=version_key)
    prev_name = None
    if args.bootstrap:
        if existing and not args.force:
            raise SystemExit("已有历史版本（%s），--bootstrap 只用于第一次" % ", ".join(existing))
    else:
        if not existing:
            raise SystemExit("没有历史清单，第一次请用 --bootstrap")
        prev_name = existing[-1]
        if version_key(version) <= version_key(prev_name) and not args.force:
            raise SystemExit("版本号必须大于上一版 %s" % prev_name)

    prev = None
    if prev_name:
        prev = read_json(MANIFESTS / ("%s.json" % prev_name), {})
        top_latest = read_json(UPDATES / "latest.json", {}) or {}
        prev["_history"] = top_latest.get("history") or []

    base = load_base(Path(args.base))
    stage = load_stage(Path(args.stage))
    out_dir = Path(args.out) if args.out else Path("E:/一键lora/output/release") / version
    result = build(base, stage, version, cfg, args.notes, prev, out_dir)

    print("RESULT: PASS")
    print(json.dumps({k: v for k, v in result.items() if k != "latest_obj"},
                     ensure_ascii=False, indent=2))
    print("完整包 %.1f MB / 增量包 %.1f MB / 变更 %d 个文件"
          % (Path(result["full"]).stat().st_size / 1048576,
             result["pack_bytes"] / 1048576, result["changed"]))
    print("下一步：把 %s 里的 full / pack / manifest / latest.json 上传到 Release v%s"
          % (out_dir, version))
    return 0


if __name__ == "__main__":
    sys.exit(main())
