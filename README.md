# Devin 简体中文语言包

**devin-language-pack-zh-hans** — 面向 Devin Desktop 的简体中文（zh-cn）本地化包。

在 VS Code 官方简体中文语言包的基础上，**补齐 667 条 Windsurf/Devin fork 专有界面字符串**，
让 Cascade、Lifeguard、Codemaps、DeepWiki、Agent Window、Devin Review、Devin 设置页等
自有界面同样显示中文，而不是回退到英文。

- 语言：简体中文（`zh-cn`）
- 目标产品：Devin Desktop（Cognition），基线版本 `1.126.0`
- 兼容引擎：`^1.126.0`
- 许可证：MIT（含上游 Microsoft MIT 内容，见 [`NOTICE.md`](NOTICE.md)）
- 依赖：**零运行时依赖**，构建仅需 Node.js ≥ 16

---

## 它和「装 VS Code 官方中文包」有什么区别

Devin Desktop 是 Code OSS 的衍生版本，它自己新增了大量界面模块。这些模块的字符串
在 Microsoft 官方语言包里**根本不存在**，因此即使装了官方中文包，这部分界面依然是英文：

| 模块前缀 | 覆盖的功能 |
| --- | --- |
| `windsurf*` | Cascade、Agent Window、Agent Spaces、Codemaps、Devin Review、Devin 设置页 |
| `lifeguard*` | Lifeguard 缺陷检查（52 条） |
| `deepwiki*` | DeepWiki |
| `devinCloud*` | Devin 云端文件 / 云端终端 / 云端会话 |
| `acp*` | ACP 远程智能体主机、会话检索 |
| `windsurfCustomColors`、`windsurfDiffColors` | 自定义主题色与差异色的设置说明 |
| `nativeHostMainService`、`installActions` | Devin CLI 安装相关提示 |

本包把这些全部译出，因此是「Devin 专用」而非「VS Code 通用」中文包。

---

## 安装

### 方式一：从 VSIX 安装（推荐）

1. 到 [Releases](../../releases) 下载最新 `.vsix`。
2. Devin Desktop 中按 `Ctrl+Shift+P` → 输入 `Install from VSIX` → 选择该文件。
3. 右下角提示出现后点击 **Change Language and Restart**；
   或手动在 `Ctrl+Shift+P` → `Configure Display Language` 中选择 **中文(简体)**。

### 方式二：命令行安装

```bash
# Windows（Devin 安装目录下的 CLI）
"<Devin 安装目录>\bin\devin-desktop.cmd" --install-extension qimen039-code.devin-language-pack-zh-hans-1.126.0.vsix

# 若此前装过上游 ms-ceintl 语言包，先卸载，避免两个包争抢 zh-cn
"<Devin 安装目录>\bin\devin-desktop.cmd" --uninstall-extension ms-ceintl.vscode-language-pack-zh-hans
```

### 方式三：自己从源码构建

```bash
git clone https://github.com/qimen039-code/devin-language-pack-zh-hans.git
cd devin-language-pack-zh-hans
node build/build.mjs          # 产出 dist/<publisher>.devin-language-pack-zh-hans-1.126.0.vsix
node build/verify.mjs         # 结构 + 覆盖率自检
```

`build.mjs` 支持覆盖参数：

```bash
node build/build.mjs --publisher your-github-name --version 1.127.0 --out ./my.vsix
```

### 可复现构建

ZIP 内嵌的是构建时刻的时间戳，默认情况下同一份源码两次构建的字节并不相同。
传入固定时间戳即可得到**字节完全一致**的产物，便于校验 Release 附件确实由本仓库源码生成：

```bash
# 方式一：显式指定
node build/build.mjs --date 2026-10-16T00:00:00Z

# 方式二：SOURCE_DATE_EPOCH（跨生态通用约定）
SOURCE_DATE_EPOCH=1792108800 node build/build.mjs
```

`build.mjs` 会打印产物的 SHA-256；`verify.mjs` 会逐条 inflate 并比对 CRC32。
Release 附件由上述命令产出并附带 `SHA256SUMS.txt`，可用同一命令重建后比对摘要。

---

## 语言包为什么有时安装失败

Devin Desktop 的扩展画廊 `marketplace.windsurf.com/vscode/...` 对源码走 Open VSX，
且在限流时会返回 `429 Too Many Requests`。IDE 内置下载器拿到错误响应后会写出一个
**被截断的文件**，报错为：

```
End of central directory record signature not found.
Either not a zip file, or file is truncated.
```

本仓库的 `.vsix` 是离线构建产物，可绕开该限流；`build/verify.mjs` 会按
ZIP 中央目录 + 逐条 CRC32 双重校验，确保交付的包不会再出现截断问题。

---

## 仓库结构

```
.
├── package.json                              # 扩展清单（contributes.localizations 在此）
├── repo.config.json                          # 构建配置（publisher / name / version / engine）
├── languagepack.png
├── translations/
│   ├── main.i18n.json                        # 核心 UI 字符串（上游基础 + 本项目 667 条覆盖）
│   ├── overrides/devin-zh-hans.json          # 本项目新增译文，逐条可审计
│   └── extensions/*.i18n.json                # 93 个内置扩展的翻译
├── vsix/
│   └── [Content_Types].xml                   # VSIX 内容类型表（清单由 build 脚本生成）
├── build/
│   ├── build.mjs                             # 零依赖打包器（自实现 ZIP + 可复现构建）
│   └── verify.mjs                            # 零依赖校验器（EOCD / CRC32 / 身份 / 覆盖率）
├── LICENSE                                   # MIT（含上游 Microsoft MIT 声明）
├── NOTICE.md                                 # 来源与制品摘要逐项列明
├── README.md
└── CHANGELOG.md
```

`translations/overrides/devin-zh-hans.json` 是本项目**唯一的人工翻译源**，
键格式为 `<模块路径>::<键名>`。`main.i18n.json` 是该文件合并进上游后的最终结果，
两者同时入库以便逐条审计。

---

## 版本策略

语言包版本号与 Devin Desktop 的 VS Code 基线版本保持一致（当前 `1.126.0`），
`engines.vscode` 亦同步为 `^1.126.0`。Devin 升级到新的 VS Code 基线后，
需要同步更新上游译文并重新构建。

---

## 贡献

1. 只修改 `translations/overrides/devin-zh-hans.json`，不要直接改 `main.i18n.json`。
2. 保留所有 `{0}`、`{1}` 等占位符与 `&&` 菜单加速键前缀。
3. 提交前运行 `node build/build.mjs && node build/verify.mjs`，两者都应为 PASS。

---

## 免责声明

本项目与 Cognition、Windsurf 或 Microsoft 均无隶属关系，也未获其背书。
仓库内仅包含字符串翻译与构建脚本，不含任何厂商二进制或私有资源。
详见 [`NOTICE.md`](NOTICE.md)。
