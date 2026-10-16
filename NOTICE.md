# 第三方内容与来源说明

本仓库是**衍生作品**，其内容可明确划分为两个来源。为保证可追溯性，此处逐项列明。

## 1. 本项目新增内容（Copyright (c) 2026 qimen039-code，MIT）

| 路径 | 说明 |
| --- | --- |
| `translations/overrides/devin-zh-hans.json` | 667 条 Windsurf/Devin fork 专有界面字符串的简体中文译文，**完全由本项目撰写** |
| `build/build.mjs` | 零依赖 VSIX 打包脚本（自实现 ZIP 写入器，支持固定时间戳的可复现构建） |
| `build/verify.mjs` | 零依赖 VSIX 结构与覆盖率自检脚本 |
| `vsix/[Content_Types].xml` | VSIX 容器内容类型表（`extension.vsixmanifest` 由 `build.mjs` 生成，不单独入库） |
| `LICENSE`（本项目版权行）、`README.md`、`CHANGELOG.md`、`NOTICE.md`、`.gitignore` | 文档与仓库配置 |
| `translations/main.i18n.json` 中被覆盖的 667 个键 | 合并后的取值来自上述 override 文件 |

## 2. 上游内容（Copyright (c) Microsoft Corporation，MIT）

| 路径 | 说明 |
| --- | --- |
| `translations/main.i18n.json` 的基础部分（约 21,336 条键） | 来自 Microsoft vscode-loc 的 `i18n/vscode-language-pack-zh-hans` |
| `translations/extensions/*.i18n.json`（93 个文件） | 同上，内置扩展的简体中文本地化 |
| `languagepack.png` | 上游语言包图标 |

- 上游仓库：<https://github.com/microsoft/vscode-loc>
- 上游语言包标识：`MS-CEINTL.vscode-language-pack-zh-hans`
- 上游版本：`1.126.0`
- 上游来源（本次构建所依据的制品）：
  `https://open-vsx.org/api/MS-CEINTL/vscode-language-pack-zh-hans/1.126.0/file/MS-CEINTL.vscode-language-pack-zh-hans-1.126.0.vsix`
- 上游制品 SHA-256：
  `c2d9f45867bcb01737fd3dbb704b71aca4b47d962e83994afdabc0c8e53bdea9`
- 上游许可：MIT（`package.json` 中声明为 `SEE MIT LICENSE IN LICENSE.md`）

上游 MIT 版权声明已原文保留于本仓库根目录 `LICENSE` 中。

## 3. 关于 Devin / Windsurf / Cognition

- Devin Desktop 是 Cognition 基于 Code Open Source (VS Code) 构建的衍生 IDE。
- 本仓库**不包含**任何 Devin、Windsurf 或 Cognition 的二进制文件、源代码、素材或私有资源。
- 本项目仅包含**字符串翻译**，这些字符串取自公开分发的 Devin Desktop 应用内的国际化键表（`nls.keys.json`）。
  翻译键名本身属于 VS Code 上游开源代码库的标识符。
- 本项目与 Cognition、Windsurf 或 Microsoft 均无隶属关系，亦未获得其背书。
- "Devin"、"Windsurf"、"Cascade"、"Cognition" 等名称是其各自所有者的商标，
  本项目对这些名称的使用仅用于**指代与说明用途**。
