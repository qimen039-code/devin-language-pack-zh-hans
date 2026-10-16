# 更新日志

本项目的版本号跟随 Devin Desktop 的 VS Code 基线版本。

---

## Web 应用覆盖层 webapp/1.0.0 — 2026-10-16

新增第二个交付物：`webapp/`（见 [`webapp/README.md`](webapp/README.md)）。
**语言包（VSIX）本身未改动，因此 `package.json` 版本保持 `1.126.1` 不变。**

### 背景

此前收到的"漏译"键（`Local Settings`、`Data retention`、`Model provider API keys`
以及 Devin Desktop 设置页整片文案）在本地安装树里**全树 0 命中**。定位结论是：
Devin Desktop 的 Sessions / Settings 界面并非本地渲染，而是把
`https://app.devin.ai` 装进沙箱 iframe 远程渲染，且该 Web 应用只带 en / ja / es / pt。

因此这一层**无法**由 VS Code 语言包覆盖 —— 键不在 nls 表里，加多少条都不生效。
本版本用「回环反向代理 + 字节级基址补丁」解决它。

### 新增

- `webapp/proxy.mjs`：零依赖反向代理（自实现 CONNECT 隧道、连接池、brotli/gzip/deflate
  解压、字符串替换、`/api/*` 透明透传、WebSocket 隧道）。只绑定 `127.0.0.1`，
  **不记录**任何请求头、Cookie、token 或正文。
- `webapp/warmup-all.mjs`：资源图闭包式预热（入口 → 动态 `import()` 分片逐层收敛），
  实测抓全 **1,830** 个分片、约 9 MB。
- `webapp/install.py` / `webapp/uninstall.py`：字节级改写 iframe 基址
  （**2 个 bundle、合计 4 处**调用点），并同步维护 `resources/app/product.json` 的
  `checksums` 表（`base64(SHA-256(file))` 去 `=` 填充）。安装目录自动探测：
  环境变量 → 状态文件 → 常见路径 → 注册表（`devin://` 协议处理器、App Paths）。
- `webapp/dict-zh.json`（人工译源）+ `webapp/zh-hans.json`（构建产物，41 条生效）+
  `build/webapp-dict.mjs`。
- `/__zh/health`、`/__zh/keys` 诊断端点；`install.py --status`。

### 根因修正（本轮追加）

初版只改了 `out/vs/sessions/sessions.desktop.main.js` 的 2 处调用点，实测**界面仍为英文**。
根因是构造该 iframe 的代码在安装树里存在**两份彼此独立的副本**：

| bundle | 基址构造器 | 调用点 | 归属 |
| --- | --- | --- | --- |
| `out/vs/sessions/sessions.desktop.main.js` | `V6r()` | `V6r(But(this._authService,this._devinService),` ×2 | Sessions 窗口 |
| `out/vs/workbench/workbench.desktop.main.js` | `oSe()` | `oSe(QC(this._authService,this._devinService),` ×2<br>`oSe(this._devinService.webUrl,` ×1 | **主窗口** |

**主窗口加载的是 `workbench.desktop.main.js`**（入口
`out/vs/code/electron-browser/workbench/workbench.js`），因此只补 sessions 那一份
不产生任何可见效果。`oSe` 是 `V6r` 的等价物，`QC` 是 `But` 的等价物，
`product.json` 的 `checksums` 表同时覆盖这两个文件，两处都必须同步。

同时修掉三个会误导使用者的问题：

- `--status` 的 `patched : N / M` 逐 edit 计数，而 workbench 的两处 edit 共用同一
  替换串 → 显示 `6 / 3`。改为按**去重后的替换串**计数。
- `product.json` 原先做文件级 `.zh-orig` 备份，且每次调用都刷新 → 第二次编辑会把
  「半打补丁」的中间态覆盖成"原版"。改为**不备份**，卸载时按还原后的 bundle 重算。
- `repo.config.json` 里冗余的 `version` 与 `package.json` 漂移（构建脚本从不读它），
  已删除并在 `build/build.mjs` 加硬守卫；README 里 `…-1.126.0.vsix` 的示例一并修正。

`oSe(this.devinService.webUrl,`（**无下划线**，用于 PR-review webview）**刻意不打** ——
它依赖绑定在 app origin 上的按源请求头鉴权，换基址会破坏其认证。

### 关键设计

- **鉴权走 URL 参数 + postMessage，不用 Cookie** → 无需自签 CA、无需 MITM、
  不解密任何认证流量。
- **缓存存上游原文，只有服务时才替换** → 词表覆盖率报告不会被自身替换结果污染，
  且一条译文不可能被应用两次。
- **同时匹配两种序列化形态**：`{"k":"English"}` 与 `` k:`English` ``（压缩后的裸键 +
  模板字面量）。两种模式都带键名，因此不会误伤遥测事件标识符或普通代码。
- 词表覆盖率实测 **41/41 命中、0 缺失**；离线自测（含逐字节窗口比对）**ALL PASS**。

### 改动

- `build/build.mjs`：打包排除表加入 `webapp`，避免覆盖层被打进 VSIX。

---

## 1.126.1

补齐 Devin fork 中仍是英文的界面字符串。

- 以安装包内的 `out/nls.metadata.json` 为权威键表，逐键比对后补译 **910 条**
  仍为英文的界面文本（此前为继承英文默认值的占位）。覆盖 163 个模块，主要有：
  - 问题报告器与屏幕截图标注：约 132 条
  - 聊天缓存调试（Cache Insights / Explorer）：约 110 条
  - 聊天错误与配额提示（速率限制、Copilot 额度）：51 条
  - 调查问卷：35 条
  - 代理主机（Agent Host）配置与 Codex / Claude 代理：约 60 条
  - 语音智能体（Agents Voice）：约 40 条
  - MCP、终端智能体工具、扩展、远程与本地化服务等其余条目。
- 补译前逐条过滤掉不应翻译的内容：格式化模板（`{0} ({1})`）、键盘按键名
  （Alt / Ctrl / Shift）、品牌名与纯符号，共 150 条保持原文。
- 新增 **26 条**由用户报告的界面键（标题栏、命令中心、编辑器操作等），
  这些键在当前 Devin 1.126.0 的本地构建中不存在，属预置翻译。
- 合并后核心字符串总量：22,003 → **22,029** 条；人工译源 667 → **1,592** 条。
- 人称统一为 VS Code 简体中文惯例（"你"而非"您"）。

## 1.126.0

首个版本。

- 以上游 `MS-CEINTL.vscode-language-pack-zh-hans@1.126.0` 为基线
  （SHA-256 `c2d9f45867bcb01737fd3dbb704b71aca4b47d962e83994afdabc0c8e53bdea9`）。
- 新增 **667 条** Windsurf/Devin fork 专有界面字符串的简体中文译文，覆盖 92 个核心模块：
  - Lifeguard 缺陷检查：52 条
  - Agent Window / Agent Spaces / 智能体命令中心：约 60 条
  - Codemaps（代码地图）：18 条
  - DeepWiki：16 条
  - Devin Cloud 文件 / 云端终端：约 20 条
  - ACP 远程智能体主机与会话检索：15 条
  - Devin Review（拉取请求审查）：14 条
  - Devin 设置页与 React 设置页：11 条
  - 自定义主题色 / 差异色说明：13 条
  - 以及内核上下文键、布局动作、更新流程、CLI 安装提示等其余条目。
- 合并后核心字符串总量：21,336 → **22,003** 条；模块数 1,806 → **1,898**。
- 内置扩展翻译保持 93 个文件不变（上游覆盖已完整，仅 2 条 `package.nls` 缺口）。
- 新增零依赖构建与校验脚本 `build/build.mjs`、`build/verify.mjs`。
- 构建脚本支持固定时间戳的可复现构建（`--date` / `SOURCE_DATE_EPOCH`），
  同一份源码可重建出字节一致的 VSIX。
- 扩展标识：`qimen039-code.devin-language-pack-zh-hans`，许可证 MIT。
