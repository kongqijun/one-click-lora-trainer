#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建期密封：把受保护文件的 SHA256 清单写回 app/tools/security.py。

与包内旧版 make_security.py 的算法完全一致（XOR + base64），区别是不再依赖
脚本自身所在目录，而是直接对"内存里的发布文件树"操作，打包脚本可以调用。
"""
from __future__ import annotations

import base64
import hashlib
import json
import re

_XOR_KEY = bytes("QiaoQiao_LoRA_Trainer_2026_!sec$", "utf-8")
_SHOP_URL = "https://lora-hub.app.workbuddy.host/"
_SHOP_HOST = "lora-hub.app.workbuddy.host"

PROTECTED_CONFIGS = (
    "app/configs/models.yaml",
    "app/configs/dataset_template.toml",
    "app/configs/lora_illustrious_8gb.toml",
)


def _xor(data: bytes) -> bytes:
    k = _XOR_KEY
    return bytes(b ^ k[i % len(k)] for i, b in enumerate(data))


def protected_files(tree: dict) -> list[str]:
    """与旧 make_security.py 相同的收集规则。"""
    out = ["一键Lora.exe", "app/lora_trainer_gui.py"]
    out += sorted(rel for rel in tree
                  if rel.startswith("app/tools/") and rel.endswith(".py")
                  and rel not in ("app/tools/security.py", "app/tools/make_security.py"))
    out += [rel for rel in PROTECTED_CONFIGS if rel in tree]
    return [rel for rel in out if rel in tree]


def seal(tree: dict) -> bytes:
    """返回密封后的 security.py 内容。tree: {相对路径: bytes}"""
    manifest = {rel: hashlib.sha256(tree[rel]).hexdigest()
                for rel in protected_files(tree)}
    url_enc = base64.b64encode(_xor(_SHOP_URL.encode())).decode("ascii")
    host_enc = base64.b64encode(_xor(_SHOP_HOST.encode())).decode("ascii")
    man_enc = base64.b64encode(
        _xor(json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode())
    ).decode("ascii")

    src = tree["app/tools/security.py"].decode("utf-8-sig")

    def _set(marker: str, val: str) -> str:
        pat = r'(_%s = ")[^"]*(")' % marker
        if not re.search(pat, src):
            raise SystemExit("security.py 缺少占位符 _%s" % marker)
        return re.sub(pat, lambda m: m.group(1) + val + m.group(2), src, count=1)

    src = _set("SHOP_URL_ENC", url_enc)
    src = _set("SHOP_HOST_ENC", host_enc)
    src = _set("INTEGRITY_ENC", man_enc)
    compile(src, "security.py", "exec")
    return src.encode("utf-8")


def verify_seal(tree: dict) -> None:
    """重新算一遍清单，确认写进 security.py 的哈希与文件一致。"""
    import ast
    src = tree["app/tools/security.py"].decode("utf-8-sig")
    values = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_INTEGRITY_ENC":
                    values[target.id] = ast.literal_eval(node.value)
    blob = _xor(base64.b64decode(values["_INTEGRITY_ENC"], validate=True))
    manifest = json.loads(blob.decode("utf-8"))
    for rel, expect in manifest.items():
        actual = hashlib.sha256(tree[rel]).hexdigest()
        if actual != expect:
            raise SystemExit("密封校验失败：%s" % rel)
