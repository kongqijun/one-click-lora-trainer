#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""更新链路自测：不联网，用本地目录模拟 GitHub Release。

跑法：python packaging/test_updater.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE = Path("E:/一键lora/review_fix_v25/stage")
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(STAGE / "app" / "tools"))

import build_release as B          # noqa: E402
import make_security               # noqa: E402
import updater                     # noqa: E402


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def make_zip(path: Path, entries: dict, prefix: str = "") -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, data in entries.items():
            z.writestr(prefix + rel, data)


class VersionTests(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("1.2.3-beta"), (1, 2, 3))
        self.assertIsNone(updater.parse_version("abc"))
        self.assertEqual(updater.compare_versions("1.2.3", "1.2.10"), -1)
        self.assertEqual(updater.compare_versions("v1.3.0", "1.2.9"), 1)
        self.assertEqual(updater.compare_versions("1.0", "1.0.0"), 0)


class ClientTests(unittest.TestCase):
    """把 updater 的路径全局量指到临时目录，模拟一次真实更新。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="yj_upd_"))
        self.root = self.tmp / "LoRA_Trainer"
        for name, val in {
            "APP": self.root / "app", "ROOT": self.root,
            "STATE": self.root / "app" / "update",
            "STAGING": self.root / "app" / "update" / "staging",
            "DOWNLOAD": self.root / "app" / "update" / "download",
            "JOURNAL": self.root / "app" / "update" / "journal.json",
            "STAGED": self.root / "app" / "update" / "staged.json",
            "INSTALLED": self.root / "app" / "update" / "installed.json",
            "LOG": self.root / "app" / "update" / "update.log",
        }.items():
            setattr(updater, name, val)
        self.v1 = {
            "app/version.json": json.dumps({"version": "1.0.0", "repo": "o/r"}).encode(),
            "app/tools/a.py": b"print('a1')\n",
            "app/tools/b.py": b"print('b')\n",
            "app/data.txt": b"data",
        }
        self.v2 = dict(self.v1)
        self.v2["app/version.json"] = json.dumps({"version": "1.0.1", "repo": "o/r"}).encode()
        self.v2["app/tools/a.py"] = b"print('a2')\n"
        self.v2["app/tools/c.py"] = b"print('c')\n"
        self.v2.pop("app/tools/b.py")
        self._install_v1()
        self.release = self._make_release("1.0.1", self.v1, self.v2)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------------------------------------------------------- helper
    def _install_v1(self):
        for rel, data in self.v1.items():
            write(self.root / rel, data)
        write(self.root / "app/task_data/t.json", b"user")
        files = {rel: sha(data) for rel, data in self.v1.items()}
        updater.write_json(updater.INSTALLED,
                           {"schema": 1, "version": "1.0.0", "files": files})

    def _make_release(self, version, old, new):
        rd = self.tmp / "release"
        manifest = {"schema": 1, "version": version,
                    "files": {rel: sha(data) for rel, data in new.items()}}
        manifest["files"]["app/update/installed.json"] = sha(
            json.dumps({"schema": 1, "version": version,
                        "files": {k: v for k, v in manifest["files"].items()
                                  if k != "app/update/installed.json"}},
                       ensure_ascii=False).encode())
        mp = rd / ("manifest-%s.json" % version)
        write(mp, json.dumps(manifest, ensure_ascii=False).encode())
        changed = {rel: data for rel, data in new.items() if old.get(rel) != data}
        changed["app/update/installed.json"] = json.dumps(
            {"schema": 1, "version": version,
             "files": {rel: sha(data) for rel, data in new.items()}},
            ensure_ascii=False).encode()
        pp = rd / ("pack-%s.zip" % version)
        make_zip(pp, changed)
        full = rd / ("full-%s.zip" % version)
        make_zip(full, new, "LoRA_Trainer/")
        latest = {
            "schema": 1, "version": version, "tag": "v" + version,
            "released": "2026-10-26", "channel": "stable", "notes": "test",
            "full_only": False,
            "full": {"url": str(full), "sha256": sha(full.read_bytes()), "size": full.stat().st_size},
            "manifest": {"url": str(mp), "sha256": sha(mp.read_bytes()), "size": mp.stat().st_size},
            "history": [
                {"version": "1.0.0", "pack": None},
                {"version": version, "from": "1.0.0",
                 "pack": {"url": str(pp), "sha256": sha(pp.read_bytes()), "size": pp.stat().st_size}},
            ],
        }
        lp = rd / "latest.json"
        write(lp, json.dumps(latest, ensure_ascii=False).encode())
        return latest, lp

    def _stage(self, release_and_latest):
        release, latest_path = release_and_latest
        res = updater.check(source=str(latest_path))
        self.assertEqual(res["status"], "update", res)
        self.assertEqual(res["plan"]["kind"], "packs")
        info = updater.download_and_stage(res["plan"], res["release"])
        return res, info

    # ---------------------------------------------------------- 用例
    def test_full_flow(self):
        res, _ = self._stage(self.release)
        self.assertFalse(updater.apply_staged_on_startup())   # 主程序没变，不需要重启
        self.assertEqual((self.root / "app/tools/a.py").read_bytes(), self.v2["app/tools/a.py"])
        self.assertTrue((self.root / "app/tools/c.py").is_file())
        self.assertFalse((self.root / "app/tools/b.py").exists())
        self.assertEqual((self.root / "app/task_data/t.json").read_bytes(), b"user")
        installed = json.loads(updater.INSTALLED.read_text("utf-8"))
        self.assertEqual(installed["version"], "1.0.1")
        self.assertIsNone(updater.staged_info())
        self.assertFalse(updater.JOURNAL.exists())

    def test_gui_change_requests_relaunch(self):
        v2 = dict(self.v2)
        v2["app/lora_trainer_gui.py"] = b"# new gui\n"
        self.release = self._make_release("1.0.1", self.v1, v2)
        self._stage(self.release)
        self.assertTrue(updater.apply_staged_on_startup())

    def test_second_apply_is_noop(self):
        self._stage(self.release)
        updater.apply_staged_on_startup()
        self.assertIsNone(updater.staged_info())
        self.assertFalse(updater.apply_staged_on_startup())

    def test_tampered_pack_is_rejected(self):
        latest, lp = self.release
        pack = Path(latest["history"][-1]["pack"]["url"])
        bad = self.tmp / "release" / "bad-pack.zip"
        make_zip(bad, {"app/tools/a.py": b"print('evil')\n",
                       "app/version.json": self.v2["app/version.json"],
                       "app/update/installed.json": json.dumps(
                           {"schema": 1, "version": "1.0.1",
                            "files": {rel: sha(d) for rel, d in self.v2.items()}},
                           ensure_ascii=False).encode()})
        pack.write_bytes(bad.read_bytes())
        latest = json.loads(json.dumps(latest))
        latest["history"][-1]["pack"]["sha256"] = sha(pack.read_bytes())
        write(lp, json.dumps(latest, ensure_ascii=False).encode())
        res = updater.check(source=str(lp))
        with self.assertRaises(updater.UpdateError):
            updater.download_and_stage(res["plan"], res["release"])
        self.assertEqual((self.root / "app/tools/a.py").read_bytes(), b"print('a1')\n")

    def test_path_traversal_rejected(self):
        self._stage(self.release)
        dest = self.tmp / "extract"
        evil = self.tmp / "evil.zip"
        make_zip(evil, {"../evil.txt": b"x"})
        with self.assertRaises(updater.UpdateError):
            updater._extract_pack(evil, dest)
        self.assertFalse((self.tmp / "evil.txt").exists())
        self.assertTrue(updater.safe_rel("app/tools/a.py"))
        self.assertFalse(updater.safe_rel("../evil.txt"))
        self.assertFalse(updater.safe_rel("C:/Windows/x.dll"))
        self.assertFalse(updater.safe_rel("app/task_data/x.json"))

    def test_rollback_restores_files(self):
        target = self.root / "app/tools/a.py"
        target.write_bytes(b"print('broken')\n")
        backup = updater.STATE / "backup_test"
        write(backup / "app/tools/a.py", self.v1["app/tools/a.py"])
        updater.write_json(updater.JOURNAL, {
            "phase": "applying", "backup": str(backup), "version": "1.0.1",
            "written": ["app/tools/a.py"], "removed": []})
        self.assertTrue(updater.rollback_pending())
        self.assertEqual(target.read_bytes(), self.v1["app/tools/a.py"])
        self.assertFalse(updater.JOURNAL.exists())

    def test_too_old_version_needs_full(self):
        write(self.root / "app/version.json", json.dumps({"version": "0.9.0"}).encode())
        res = updater.check(source=str(self.release[1]))
        self.assertEqual(res["status"], "update")
        self.assertEqual(res["plan"]["kind"], "full")

    def test_latest_version_no_update(self):
        write(self.root / "app/version.json", json.dumps({"version": "1.0.1"}).encode())
        res = updater.check(source=str(self.release[1]))
        self.assertEqual(res["status"], "latest")

    def test_full_only(self):
        latest, lp = self.release
        latest = json.loads(json.dumps(latest))
        latest["full_only"] = True
        write(lp, json.dumps(latest, ensure_ascii=False).encode())
        res = updater.check(source=str(lp))
        self.assertEqual(res["plan"]["kind"], "full")


class BuildTests(unittest.TestCase):
    """构建脚本：密封 + 完整包 + 增量包 + 校验。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="yj_build_"))
        self.repo = self.tmp / "repo"
        B.UPDATES = self.repo / "updates"
        B.MANIFESTS = B.UPDATES / "manifests"
        B.MANIFESTS.mkdir(parents=True)
        self.cfg = {"repo": "o/r", "channel": "stable"}

        sec = (STAGE / "app/tools/security.py").read_bytes()
        self.base_tree = {
            "app/tools/security.py": sec,
            "app/tools/foo.py": b"x=1\n",
            "app/lora_trainer_gui.py": b"# gui\n",
            "app/configs/models.yaml": b"models: []\n",
            "python/python.exe": b"MZ fake",
            "一键Lora.exe": b"MZ launcher",
        }
        self.base_zip = self.tmp / "base.zip"
        sums = {rel: sha(data) for rel, data in self.base_tree.items()}
        entries = dict(self.base_tree)
        entries["SHA256SUMS.json"] = json.dumps(sums).encode()
        make_zip(self.base_zip, entries, "LoRA_Trainer/")

        self.stage = self.tmp / "stage"
        for rel, data in {
            "app/tools/security.py": sec,
            "app/tools/foo.py": b"x=1\n",
            "app/tools/bar.py": b"y=2\n",
            "app/lora_trainer_gui.py": b"# gui\n",
            "app/configs/models.yaml": b"models: []\n",
        }.items():
            write(self.stage / rel, data)
        write(self.stage / "tokenizers/tok.json", b"{}")
        write(self.stage / "一键Lora.exe", b"MZ launcher")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bootstrap_and_delta(self):
        base = B.load_base(self.base_zip)
        stage = B.load_stage(self.stage)
        out1 = self.tmp / "out1"
        r1 = B.build(base, stage, "1.0.0", self.cfg, "", None, out1)
        self.assertIsNone(r1["pack"])
        tree = dict(base)
        tree.update(stage)

        # 包内 security.py 必须通过完整性校验
        pkg = self.tmp / "pkg100"
        with zipfile.ZipFile(out1 / "YijianLoRA-full-v1.0.0.zip") as z:
            z.extractall(pkg)
            installed = json.loads(z.read("LoRA_Trainer/app/update/installed.json"))
            self.assertEqual(installed["version"], "1.0.0")
            self.assertIn("app/tools/bar.py", installed["files"])
            self.assertNotIn("app/update/installed.json", installed["files"])
            sums = json.loads(z.read("LoRA_Trainer/SHA256SUMS.json"))
            self.assertNotIn("SHA256SUMS.json", sums)
        root = pkg / "LoRA_Trainer"
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sec_built", root / "app/tools/security.py")
        sec_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sec_mod)
        self.assertEqual(sec_mod.verify_integrity(str(root)), [])

        # 第二版：改 foo.py，增量包应包含它 + 重新密封的 security.py
        write(self.stage / "app/tools/foo.py", b"x=42\n")
        stage2 = B.load_stage(self.stage)
        prev = json.loads((B.MANIFESTS / "1.0.0.json").read_text("utf-8"))
        prev["_history"] = json.loads((B.UPDATES / "latest.json").read_text("utf-8"))["history"]
        out2 = self.tmp / "out2"
        r2 = B.build(base, stage2, "1.0.1", self.cfg, "fix", prev, out2)
        self.assertTrue(r2["pack"])
        with zipfile.ZipFile(r2["pack"]) as z:
            names = set(z.namelist())
        self.assertIn("app/tools/foo.py", names)
        self.assertIn("app/tools/security.py", names)
        self.assertIn("app/version.json", names)
        self.assertIn("app/update/installed.json", names)
        self.assertNotIn("python/python.exe", names)
        self.assertIn("1.0.1", (B.UPDATES / "latest.json").read_text("utf-8"))


    def test_client_applies_delta_and_integrity_holds(self):
        """真实链路：v1.0.0 完整包 → 应用 v1.0.1 增量 → 启动自检仍然通过。"""
        base = B.load_base(self.base_zip)
        stage = B.load_stage(self.stage)
        out1 = self.tmp / "out1"
        B.build(base, stage, "1.0.0", self.cfg, "", None, out1)

        client = self.tmp / "client"
        with zipfile.ZipFile(out1 / "YijianLoRA-full-v1.0.0.zip") as z:
            z.extractall(client)
        root = client / "LoRA_Trainer"

        for name, val in {
            "APP": root / "app", "ROOT": root,
            "STATE": root / "app" / "update",
            "STAGING": root / "app" / "update" / "staging",
            "DOWNLOAD": root / "app" / "update" / "download",
            "JOURNAL": root / "app" / "update" / "journal.json",
            "STAGED": root / "app" / "update" / "staged.json",
            "INSTALLED": root / "app" / "update" / "installed.json",
            "LOG": root / "app" / "update" / "update.log",
        }.items():
            setattr(updater, name, val)

        write(self.stage / "app/tools/foo.py", b"x=99\n")
        stage2 = B.load_stage(self.stage)
        prev = json.loads((B.MANIFESTS / "1.0.0.json").read_text("utf-8"))
        prev["_history"] = json.loads((B.UPDATES / "latest.json").read_text("utf-8"))["history"]
        out2 = self.tmp / "out2"
        r2 = B.build(base, stage2, "1.0.1", self.cfg, "fix", prev, out2)

        # 把 GitHub 地址换成本机路径，模拟下载
        latest = json.loads((out2 / "latest.json").read_text("utf-8"))
        latest["full"] = {"url": str(out2 / "YijianLoRA-full-v1.0.1.zip"),
                          "sha256": sha((out2 / "YijianLoRA-full-v1.0.1.zip").read_bytes()),
                          "size": (out2 / "YijianLoRA-full-v1.0.1.zip").stat().st_size}
        latest["manifest"] = {"url": str(out2 / "YijianLoRA-manifest-v1.0.1.json"),
                              "sha256": sha((out2 / "YijianLoRA-manifest-v1.0.1.json").read_bytes()),
                              "size": (out2 / "YijianLoRA-manifest-v1.0.1.json").stat().st_size}
        for h in latest["history"]:
            if h.get("pack"):
                p = Path(r2["pack"])
                h["pack"] = {"url": str(p), "sha256": sha(p.read_bytes()), "size": p.stat().st_size}
        lp = self.tmp / "latest-local.json"
        write(lp, json.dumps(latest, ensure_ascii=False).encode())

        res = updater.check(source=str(lp))
        self.assertEqual(res["status"], "update")
        self.assertEqual(res["plan"]["kind"], "packs")
        info = updater.download_and_stage(res["plan"], res["release"])
        self.assertGreater(info["files"], 0)
        updater.apply_staged_on_startup()

        self.assertEqual((root / "app/tools/foo.py").read_bytes(), b"x=99\n")
        self.assertEqual(json.loads((root / "app/version.json").read_text("utf-8"))["version"], "1.0.1")

        import importlib.util
        spec = importlib.util.spec_from_file_location("sec_client", root / "app/tools/security.py")
        sec_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sec_mod)
        self.assertEqual(sec_mod.verify_integrity(str(root)), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
