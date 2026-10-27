# 一键LoRA · GitHub 发布与增量更新流程

本文是给发布者（你自己）看的操作手册。按顺序执行即可；每一步都写了"怎么确认做对了"。

---

## 0. 结论先看：这套更新是怎么工作的

- 每次发版，客户端**不下载完整包**，只下载"从你当前版本到最新版本"之间**真正变过的文件**，打包成一个几 MB 的增量包（pack）。
- 判断哪些文件变了，靠的是包内每个文件的 SHA256 清单（manifest）。清单由构建脚本生成，不需要手工维护。
- 客户端只从 GitHub 的 **Release 下载地址**取文件，**不调用 GitHub API**（本机 `api.github.com` 会返回 403，走 API 的方案在你这台机器上直接废掉）。
- 完整包仍然发布，但只在两种情况下用到：首次安装、跨版本太远（增量链断了）、或者这次改动涉及 `python/` 和 `一键Lora.exe`（运行中被占用，不能热替换）。
- `security.py` 里的完整性清单每次发版都会重新密封，并随增量包一起下发；否则客户端更新完会被自己的完整性校验拦住。

### 目录约定

| 位置 | 用途 | 是否进 Git |
|---|---|---|
| `E:\一键lora\review_fix_v25\stage` | 开发工作区（当前版本源码） | 否 |
| `E:\一键lora\release_repo` | 发布工程：构建脚本 + 版本号 + 历史清单 | 是（推送到公开仓） |
| `E:\一键lora\output\release\<版本>` | 每次构建出的 4 个发布产物 | 否（上传到 Release） |
| `E:\一键lora\output\*.zip` | 完整安装包归档 | 否 |

> 公开仓**不放源码**，只放 `updates/` 下的版本清单和 Release 资产。源码继续留在本机（需要备份的话，另建一个私有仓，见附录 A）。

---

## 1. 一次性准备：创建公开的"发布仓库"

仓库已经建好：**https://github.com/kongqijun/one-click-lora-trainer**（公开仓，匿名访问返回 200，已确认）。

后面所有地方都用仓库全名 `kongqijun/one-click-lora-trainer`。

### 1.1 本地初始化并关联

```powershell
cd E:\一键lora\release_repo
git init -b main
git remote add origin https://github.com/kongqijun/one-click-lora-trainer.git
```

首次 `push` 会弹出浏览器让你登录 GitHub。登录一次后 Windows 凭据管理器会记住。

### 1.2 仓库名（已填好，无需再改）

[release.json](E:/一键lora/release_repo/packaging/release.json) 已经指向最终仓库，内容如下：

```json
{
  "repo": "kongqijun/one-click-lora-trainer",
  "channel": "stable",
  "version": "1.0.0"
}
```

这个文件是**唯一的版本号来源**。构建时它会写进包内的 `app/version.json`，客户端就靠它判断"我现在是几版"。

---

## 2. 版本号规则（怎么对齐）

### 2.1 只有一处需要改

**每次发版只改 `packaging/release.json` 里的 `version`。** 其他所有地方都由构建脚本生成：

| 地方 | 来源 |
|---|---|
| 包内 `app/version.json` | 构建时写入 |
| 完整包文件名 `YijianLoRA-full-v1.0.1.zip` | 构建时生成 |
| 增量包文件名 `YijianLoRA-pack-v1.0.1.zip` | 构建时生成 |
| Release 标签 `v1.0.1` | 上传时用同名标签 |
| `latest.json` 里的 `version` / `tag` | 构建时生成 |
| 客户端"关于/检查更新"显示 | 读 `app/version.json` |
| `updates/manifests/1.0.1.json` | 构建时生成 |

不存在"手改一处忘了另一处"的问题。

### 2.2 三段式含义

版本格式固定 `主.次.修`（如 `1.2.3`）：

| 位 | 什么时候加 | 例子 |
|---|---|---|
| 主版本 | 包结构变了、必须重装完整包（换 Python 运行时、换目录布局） | `1.9.0 → 2.0.0` |
| 次版本 | 加功能、加底模支持 | `1.2.0 → 1.3.0` |
| 修订号 | 只修 bug、改文案 | `1.2.3 → 1.2.4` |

**版本号必须递增**，构建脚本会拒绝小于等于历史清单里最大版本的号。

### 2.3 标签必须等于版本号

Release 的标签统一写 `v` + 版本号（`v1.0.1`）。脚本生成的下载地址就是按这个标签拼的，**标签写错客户端就 404**。

---

## 3. 首次发布 1.0.0（基线包）

第一次没有"上一版"，所以只能出完整包，不能出增量包。

```powershell
cd E:\一键lora\release_repo

python packaging\build_release.py `
  --bootstrap `
  --stage "E:\一键lora\review_fix_v25\stage" `
  --base "E:\一键lora\output\一键LoRA_最新完整包_20261023_182135.zip"
```

参数说明：

- `--stage`：当前开发工作区（脚本从这里取 `app/`、`tokenizers/`、`一键Lora.exe`）。
- `--base`：上一个完整包，脚本从里面取 `python/` 和 `Mock无现金/` 这类不常改的运行环境。
- `--bootstrap`：表示这是第一版，只出完整包 + 清单，不出增量包。

成功后终端会打印 4 个产物路径，都在 `E:\一键lora\output\release\1.0.0\`：

```
YijianLoRA-full-v1.0.0.zip          完整包（约 110 MB）
YijianLoRA-manifest-v1.0.0.json     文件清单（客户端校验用）
latest.json                          更新指针
```

（基线版没有增量包，从 1.0.1 开始才有。）

### 3.1 上传 Release

1. 浏览器打开 `https://github.com/kongqijun/one-click-lora-trainer/releases/new`。
2. **Choose a tag** 输入 `v1.0.0` → 点 "Create new tag: v1.0.0 on publish"。
3. Release title 填 `v1.0.0`。
4. 把 `E:\一键lora\output\release\1.0.0\` 里的 **3 个文件**（full、manifest、latest.json）拖进 "Attach binaries"。
5. 正文里写这次更新了什么（客户端会显示 `notes`，但正文只给人看）。
6. 确认**没有**勾 "Set as a pre-release"，点 **Publish release**。
7. 发布后确认它是仓库的 Latest release（仓库首页右侧应显示 v1.0.0）。

### 3.2 提交清单到仓库（给下一版算增量用）

```powershell
cd E:\一键lora\release_repo
git add updates README.md packaging
git commit -m "release: v1.0.0 基线"
git push -u origin main
```

### 3.3 验证

浏览器直接打开：

```
https://github.com/kongqijun/one-click-lora-trainer/releases/latest/download/latest.json
```

能看到 JSON、`version` 是 `1.0.0`，就算通了。**这一步不通，后面所有更新都不会通。**

然后：

- 用 1.0.0 完整包解压一份，双击启动，确认菜单里显示 `v1.0.0`；
- 点"检查更新"，应提示"已是最新版本"。

> 老用户（v26 及以前）没有 `app/version.json`，客户端会提示"无法识别当前版本，请下载完整包"。他们把 1.0.0 完整包解压覆盖一次即可，用户数据（任务记录、配置、模型）不会被覆盖。

---

## 4. 日常发版（以 1.0.1 为例）

只改了一处：`packaging/release.json` 里的版本号。

### 第 1 步：改版本号

```json
{ "version": "1.0.1" }
```

### 第 2 步：构建

```powershell
cd E:\一键lora\release_repo

python packaging\build_release.py `
  --stage "E:\一键lora\review_fix_v25\stage" `
  --base "E:\一键lora\output\一键LoRA_最新完整包_20261023_182135.zip"
```

（`--base` 永远指向上一个**完整包**，不用每次换。）

脚本会：

1. 把 stage 的 `app/`、`tokenizers/`、`一键Lora.exe` 覆盖到 base 包的文件树上；
2. 写入 `app/version.json`；
3. 重新密封 `app/tools/security.py`（保护清单跟着变）；
4. 生成 `app/update/installed.json`（本版完整文件清单，客户端靠它算"哪些文件要删"）；
5. 与 `updates/manifests/1.0.0.json` 对比，把变化的文件打进增量包；
6. 逐文件校验产物，任何一项对不上直接失败。

成功输出：

```
release/1.0.1/
  YijianLoRA-full-v1.0.1.zip
  YijianLoRA-pack-v1.0.1.zip         ← 这次真正要下载的东西（通常几百 KB ~ 几 MB）
  YijianLoRA-manifest-v1.0.1.json
  latest.json
```

终端还会打印增量包体积和文件数。**如果增量包接近完整包体积，说明改动碰到了大文件（素材、sd-scripts），先确认是不是预期内的。**

### 第 3 步：上传 Release

同 3.1，标签改成 `v1.0.1`，把 4 个文件全部拖上去，确保是 Latest release。

### 第 4 步：提交新清单

```powershell
git add updates packaging/release.json
git commit -m "release: v1.0.1"
git push
```

### 第 5 步：验证（必做）

1. 拿一份 1.0.0 的安装，启动 → 菜单里应出现"发现新版本 v1.0.1"。
2. 点更新 → 进度条走完 → 提示"重启后生效"。
3. 重启 → 版本变成 `v1.0.1`，功能正常。
4. 看 `app\update\` 目录：`staging`、`backup_*`、`journal.json` 都不应残留（成功后被清掉）。

---

## 5. 更新协议（客户端到底请求了什么）

### 5.0 客户端入口

- 启动 2.5 秒后**静默检查**一次：有新版本时顶栏出现「发现新版本 v1.0.1」按钮；没有就什么都不显示。
- 头像菜单 →「检查更新（v当前版本）」：强制重新检查并弹对话框。
- 发现新版本 → 下载并校验到暂存区 → 提示「重启后生效」→ 立即重启或稍后手动重启。
- 应用发生在**下一次启动的最开始**（导入其它模块之前），中途失败会自动回滚到旧版本。

### 5.1 检查更新

按顺序尝试，第一个成功的就用：

1. `https://github.com/<repo>/releases/latest/download/latest.json`
2. `https://cdn.jsdelivr.net/gh/<repo>@main/updates/latest.json`
3. `https://raw.githubusercontent.com/<repo>/main/updates/latest.json`

> 第 1 个是 Release 资产，永远是最新且不走 API；第 2、3 个是仓库文件，作为被墙/超时的兜底（jsDelivr 有缓存，可能滞后十几分钟）。
> 调试或临时换源：设置环境变量 `LORA_UPDATE_SOURCE` 指向一个 `latest.json` 的 URL，或本机目录。

`latest.json` 结构：

```json
{
  "schema": 1,
  "version": "1.0.1",
  "tag": "v1.0.1",
  "released": "2026-10-28",
  "channel": "stable",
  "notes": "修复 WD14 在部分环境下的报错",
  "full_only": false,
  "full": {
    "url": "https://github.com/OWNER/REPO/releases/download/v1.0.1/YijianLoRA-full-v1.0.1.zip",
    "sha256": "…",
    "size": 112345678
  },
  "manifest": {
    "url": "https://github.com/OWNER/REPO/releases/download/v1.0.1/YijianLoRA-manifest-v1.0.1.json",
    "sha256": "…",
    "size": 2345678
  },
  "history": [
    { "version": "1.0.0", "pack": null },
    { "version": "1.0.1", "from": "1.0.0",
      "pack": { "url": "…/YijianLoRA-pack-v1.0.1.zip", "sha256": "…", "size": 1234567 } }
  ]
}
```

### 5.2 选路

- 本地版本 == 最新版本：提示已是最新；用户可手动"校验文件"（逐个哈希比对，发现问题下载完整包）。
- 本地版本 < 最新版本：
  - `full_only: true` → 引导下载完整包（运行中的 Python/exe 无法热替换）；
  - 本地版本在 `history` 里 → 下载它之后每一版的 pack，全部解到暂存目录；
  - 本地版本不在 `history` 里（太旧） → 下载完整包。
- 本地版本 > 最新版本（测试版/内测）：不降级。

### 5.3 应用规则

1. 以**最新版的 manifest** 为唯一标准：清单里的文件就是最终状态。
2. 暂存目录里有该文件 → 用暂存文件；否则本地文件哈希已经等于清单值 → 保持不动；否则视为缺文件，回退完整包。
3. 本地 `installed.json` 里有、而新清单里没有的文件 → 删除（这是"删文件"的唯一依据）。
4. 清单之外的一切（`task_data/`、`configs/env.json`、`output/`、模型、训练环境）**绝不触碰**。
5. 应用前把被覆盖的文件备份到 `app/update/backup_<时间>/`，并写 `journal.json`；全部成功后删 journal。下次启动若发现 journal，先整体回滚再启动——所以更新中断不会把程序搞坏。
6. 每个文件写入前校验 SHA256；路径拒绝 `..`、绝对路径、盘符/ADS、指向包外的符号链接。

### 5.4 完整性密封

`app/tools/security.py` 里的保护清单包含所有 `app/tools/*.py` 和 `app/lora_trainer_gui.py`。所以：

- 每次构建都重新密封，密封后的 `security.py` **打进增量包**；
- 客户端应用更新时会一起替换，启动自检自然通过；
- 如果只手工替换了某个 `tools/*.py` 而没有重新密封，启动会被拦截——这是预期行为，别绕过，重新构建发版即可。

---

## 6. 发布前检查清单

- [ ] `packaging/release.json` 的 `version` 已递增，且与要打的标签一致
- [ ] `build_release.py` 最后打印 `RESULT: PASS`（含逐文件校验）
- [ ] 增量包体积合理（几 MB 以内；超过 20MB 先查明原因）
- [ ] Release 标签为 `v<version>`，且是 Latest release（不是 draft / pre-release）
- [ ] 4 个资产都在（full / pack / manifest / latest.json）
- [ ] `latest.json` 里的下载链接点开能下（浏览器直接试）
- [ ] `updates/manifests/<version>.json` 已提交并推送
- [ ] 用上一版安装实测一次"检查 → 更新 → 重启 → 版本变化"

---

## 7. 常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| 客户端报"检查更新失败" | 三个源都不通 | 浏览器试 `releases/latest/download/latest.json`；能开就是客户端网络代理问题 |
| 下载 404 | 标签不是 `v<version>`，或资产没传 | 对照 `latest.json` 里的 URL 逐个点 |
| 提示"需要完整包" | 本地版本不在 history / full_only / 增量链断 | 正常兜底，下载完整包覆盖安装 |
| 更新后启动被完整性校验拦住 | 增量包里没带新的 `security.py`，或构建时没密封 | 重新构建；不要手工改包内文件 |
| 更新后版本号没变 | 更新只下载未应用（需重启） | 关闭程序重新打开；检查 `app/update/journal.json` 是否存在 |
| jsDelivr 返回旧版本 | CDN 缓存 | 主源是 Release 资产，不应走到这里；确认 Release 是 Latest |
| `git push` 报 403 | 用了密码而不是凭据 | 删除 Windows 凭据里的 github 条目，重新 push 走浏览器登录；或改用 PAT |
| 上传 100MB 包中断 | 浏览器上传不稳定 | 重试；GitHub 单文件上限 2GB，不是大小问题 |

---

## 附录 A：源码备份（可选，不影响更新）

公开仓只放发布产物。想把源码也备份到 GitHub，另建一个 **Private** 仓库，把 `E:\一键lora\release_repo` 的 `packaging/` 和 `stage/app` 推上去即可；它与更新链路完全独立，公开仓的发布流程不受影响。

## 附录 B：术语

- **完整包**：和现在一样的整包 zip，解压即用。
- **增量包（pack）**：只含"相对上一版变化了的文件"的 zip，客户端解压后覆盖。
- **manifest**：`{相对路径: SHA256}` 的完整文件清单。
- **installed.json**：包内记录"本版包含哪些文件"的清单，客户端用它判断文件该不该删。
- **密封**：把文件哈希表加密写回 `security.py` 的过程。
