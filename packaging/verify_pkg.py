#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""验收一个完整包：解压 → 版本号 → 完整性密封 → installed.json 逐文件哈希。

用法：
  python packaging/verify_pkg.py "E:\一键lora\output\release\1.0.0\YijianLoRA-full-v1.0.0.zip"
  python packaging/verify_pkg.py <包.zip> --keep E:\一键lora\output\_verify_extract   # 保留解压结果
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("package")
    ap.add_argument("--keep", default=None)
    args = ap.parse_args()

    pkg = Path(args.package)
    if not pkg.is_file():
        raise SystemExit("找不到包：%s" % pkg)
    tmp = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="yj_verify_"))
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        with zipfile.ZipFile(pkg) as z:
            names = z.namelist()
            z.extractall(tmp)
        tops = {n.split("/")[0] for n in names if n.strip("/")}
        if tops != {"LoRA_Trainer"}:
            print("VERIFY: FAIL（包内顶层目录应为 LoRA_Trainer，实际 %s）" % sorted(tops))
            return 1
        root = tmp / "LoRA_Trainer"

        ver = json.loads((root / "app/version.json").read_text("utf-8"))
        print("version:", json.dumps(ver, ensure_ascii=False))

        spec = importlib.util.spec_from_file_location("sec_pkg", root / "app/tools/security.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        bad = mod.verify_integrity(str(root))
        print("integrity:", "OK" if not bad else bad)

        inst_path = root / "app/update/installed.json"
        if not inst_path.is_file():
            print("VERIFY: FAIL（缺少 app/update/installed.json）")
            return 1
        inst = json.loads(inst_path.read_text("utf-8"))
        missing, mismatch = [], []
        for rel, want in inst["files"].items():
            p = root / rel
            if not p.is_file():
                missing.append(rel)
            elif sha256_file(p) != want:
                mismatch.append(rel)
        print("installed: %s / %d 个文件" % (inst.get("version"), len(inst["files"])))
        print("missing: %d  mismatch: %d" % (len(missing), len(mismatch)))
        for rel in (missing + mismatch)[:10]:
            print("  !", rel)

        ok = not bad and not missing and not mismatch
        print("VERIFY:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
