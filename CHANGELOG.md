# 更新日志

本项目的版本号跟随 Devin Desktop 的 VS Code 基线版本。

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
