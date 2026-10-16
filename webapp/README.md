# Devin Web 应用简中覆盖层（webapp overlay）

Devin Desktop 的 **Sessions / Settings** 界面不是 IDE 本地渲染的，而是把
`https://app.devin.ai` 装进一个沙箱 iframe 里远程渲染。因此
`translations/` 里的 VS Code 语言包**结构上无法**覆盖它 —— 那些字符串不在
nls 键表里，加多少条都不会生效。

本目录用另一条路解决它：

```
Devin Desktop (Electron)
  └─ 主窗口 / Sessions 窗口
       └─ <iframe src="http://127.0.0.1:5175/...">   ← 由 install.py 改写基址
            └─ proxy.mjs 反向代理
                 └─ https://app.devin.ai （实时上游，缓存镜像）
                      ↑ 逐条替换字符串后再回给 iframe
```

### 两个宿主，各有一套平行的实现

构造该 iframe 的代码在安装树里存在**两份彼此独立的副本**，两处都要改，
少改一处就会出现「补丁明明在位、界面还是英文」：

| bundle | 基址构造器 | 调用点 |
| --- | --- | --- |
| `out/vs/sessions/sessions.desktop.main.js` | `V6r()` | `V6r(But(this._authService,this._devinService),` ×2 |
| `out/vs/workbench/workbench.desktop.main.js` | `oSe()` | `oSe(QC(this._authService,this._devinService),` ×2（桌面导航外壳）<br>`oSe(this._devinService.webUrl,` ×1（Devin Sidebar） |

**主窗口加载的是 `workbench.desktop.main.js`**（入口
`out/vs/code/electron-browser/workbench/workbench.js`），`sessions` 那份另属
Sessions 窗口。`oSe` 是 `V6r` 的等价物，`QC` 是 `But` 的等价物 ——
同样的 origin 守卫、同样的 `webappHost` → `webUrl` 解析。

> 注意：`workbench.desktop.main.js` 内部**另有一个同名的 `V6r(r,i)`**，
> 那是无关的字符串截断辅助函数（`r.length<=i ? r : r.substring(0,i-1)+"…"`），
> 不要与 `sessions` 里的 URL 构造器混淆。

`oSe(this.devinService.webUrl,`（**无下划线**）用于 PR-review webview，
**刻意不改** —— 它依赖绑定在 app origin 上的按源请求头鉴权，换基址会破坏其认证。

## 为什么不需要证书、不需要解密流量

`app.devin.ai` 的鉴权走 **URL 参数 + postMessage**，而不是 Cookie：

- iframe 地址带 `?embedAuth=postmessage&embedded=1&theme=...&surfaceId=...&nonce=...`
- Devin 主进程再通过 `postMessage` 把会话 token 交给 iframe（`deliverAuth`）

所以只要让 iframe 的**基址**指向本地，完整流程就能照常跑通：浏览器用明文 HTTP
访问回环地址，本进程用普通 HTTPS 客户端访问上游。**没有自签 CA，没有 MITM，
不解密任何认证流量。**

## 文件

| 文件 | 作用 |
| --- | --- |
| `proxy.mjs` | 零依赖反向代理。回环专用，缓存上游原文，服务时做字符串替换 |
| `dict-zh.json` | **人工译源**（唯一需要手改的文件） |
| `zh-hans.json` | 构建产物，代理实际读取的词表。`{ key: { en, zh } }` |
| `install.py` | 字节级补丁：改写 **2 个** bundle 的 iframe 基址（合计 4 处）+ 同步 `product.json` 校验值 |
| `uninstall.py` | 从 `.zh-orig` 备份还原两个 bundle，再按还原结果**重算** `product.json` 校验值 |
| `warmup-all.mjs` | 闭包式预热：把整个 Vite 资源图抓进缓存 |
| `make-fixture.mjs` / `test-proxy.mjs` | 离线自测：夹具生成 + 代理行为校验（完全不联网） |

## 用法

```bash
# 1. 启动覆盖层代理（回环，常驻）
node webapp/proxy.mjs --port 5175

# 2. 首次把资源图抓进缓存（约 1,830 个分片，~9 MB）
node webapp/warmup-all.mjs --port 5175

# 3. 打补丁（Devin 可以开着，重启后生效）
python webapp/install.py --port 5175

# 4. 查看状态 / 还原
python webapp/install.py --status
python webapp/uninstall.py
```

配套的 Windows 启动器在仓库之外，会按顺序做「起代理 → 打补丁 → 启动 Devin」。

### 补丁到底改了什么

共 **4 处**调用点（分布在 2 个 bundle），把 iframe 基址从一个运行时计算值换成本地字面量：

```diff
  # sessions.desktop.main.js
- V6r(But(this._authService,this._devinService), ...)
+ V6r("http://127.0.0.1:5175", ...)

  # workbench.desktop.main.js
- oSe(QC(this._authService,this._devinService), ...)
+ oSe("http://127.0.0.1:5175", ...)
- oSe(this._devinService.webUrl, ...)
+ oSe("http://127.0.0.1:5175", ...)
```

`But()` / `QC()` 本身只读套餐信息并返回 `https://<webappHost>`，没有副作用，
所以替换是安全的。文件按**字节**处理，从不解码，因此不会破坏任何编码。

替换不会触发 `V6r` / `oSe` 的 origin 守卫（`origin` 不等时回退 `about:blank`）：
该 iframe 加载的路由都是**相对路径**（`/desktop-no-surfaces`、`surface.path`），
换成回环基址后基址与 URL 仍同源。CSP 也不是硬编码的 ——
`frame-src` 由 URL 自身派生（`new URL(...).origin`），所以不会拦回环地址。

`resources/app/product.json` 里的 `checksums` 表覆盖了 **两个** bundle
（`vs/sessions/sessions.desktop.main.js` 与 `vs/workbench/workbench.desktop.main.js`）。
改完 bundle 必须同步改对应项，否则完整性校验会把安装判为损坏：

```python
base64(SHA-256(file))            # 去掉尾部 '=' 填充
```

`install.py` / `uninstall.py` 会自动维护它。`product.json` **不做文件级备份**：
卸载时按**还原后的 bundle 重算**该表 —— 若改成备份文件，第二次编辑就会把
「半打补丁」的中间态存成"原版"，还原后表与 bundle 不符。写入前先把原文读进
内存，校验失败即从内存回滚。

## 词表是怎么匹配的

上游 bundle 有**两种**序列化形态，缺一不可：

```js
// 形态 1：按语言分片的大资源表
{"localSettings":"Local Settings"}

// 形态 2：压缩后的组件级标签表（裸键 + 模板字面量）
backToOrganization:`Back to organization`
```

代理对每条词条同时生成这两种模式。两种模式都**带键名**，所以替换不会误伤
同名的遥测事件标识符（如 `SettingsServiceUserAutomationsAutomation...`）或普通代码。

译源 → 词表的构建：

```bash
node build/webapp-dict.mjs <harvested-pairs.json> webapp/zh-hans.json
```

`_enOverride` 用于收录在缓存里尚未出现的英文原文（远程分片更新后一般就能自动补上）。

## 诊断

| 端点 | 用途 |
| --- | --- |
| `/__zh/health` | 词表条数、缓存目录、请求/改写计数 |
| `/__zh/keys` | 逐键命中次数；未命中键分为「裸文本」/「完全不存在」两类 |

```bash
curl -s http://127.0.0.1:5175/__zh/health
curl -s http://127.0.0.1:5175/__zh/keys
```

`/__zh/keys` 读的是**缓存里的上游原文**，不是改写后的结果，因此报告不会被自己的
替换结果污染 —— 这是缓存必须存原文、只有服务时才改写的原因。

## 自测

完全不联网，可在提交前随时跑：

```bash
node webapp/make-fixture.mjs <临时目录> --cache <rawCacheDir>
node webapp/test-proxy.mjs   <临时目录>
```

夹具会同时写入两种序列化形态，并嵌入**一段真实 bundle 的逐字节窗口**。
测试除了逐条断言替换结果，还会把那段窗口做完全相同的替换后逐字节比对，
以此证明代理没有动过相邻的任何字节。期望的改写次数从夹具字节**动态推导**，
所以词表增删后测试不会失效。

## 上游连接

代理**不假定任何特定的本机代理配置**。默认 `--upstream-proxy auto` 会按下面顺序决定：

1. 环境变量 `HTTPS_PROXY` / `https_proxy` / `HTTP_PROXY` / `http_proxy` /
   `ALL_PROXY` / `all_proxy` 中第一个**协议为 `http:`** 的值 —— 用它做 CONNECT 隧道；
2. 都没有 → **直连**。

也可显式指定：`--upstream-proxy proxy.example:3128` 或 `--upstream-proxy none`。
（`socks5://` 需要另一种 agent，因此会被忽略而不是报模糊错误。）

启动器正是靠这一点实现「代理可用时走代理、不可用时完全直连」：
它在起覆盖层之前先决定好 `HTTP(S)_PROXY` 并导出，覆盖层直接继承。

## 隐私

- 只绑定 `127.0.0.1`。
- **绝不记录**请求/响应头、Cookie、token、请求体或响应体。只记 method / path /
  status / 改写计数。
- 缓存只存静态资源（`/assets/*.js`）。`/api/*`、路由、SSE、下载一律**实时透传**，
  不缓冲、不缓存、不检查。
- 缓存目录在 `%LOCALAPPDATA%\Devin\zh-webapp-cache`，可随时删除（下次会重新抓）。

## 已知边界

1. **词表是覆盖式的，不是全量。** 上游约有 9,700 条界面键；本目录目前只收录
   导航栏 + Devin Desktop 设置页这一片。未收录的键保持英文 —— 这是正常的，
   不是故障。加键只需改 `dict-zh.json` 再重建。
2. **上游会持续发版。** 分片内容变了要重新预热（`warmup-all.mjs`）；
   新增的界面文案需要补进译源。
3. **Devin 每次升级都会覆盖 bundle。** 升级后重新跑一次 `install.py` 即可
   （它会刷新 `.zh-orig` 备份，避免用旧构建回滚）。`install.py` 会把出厂校验值
   记进状态文件，卸载时与 `product.json` 比对；不一致说明 Devin 升过级 ——
   这是预期情况，不是错误。
4. **补丁按版本失效：换版本必须重跑 `install.py`。** 基址字面量的上下文
   （`V6r(But(...))` / `oSe(QC(...))`）若被上游改写，`--status` 会报
   `original : N left` 且校验值不匹配，据此即可判定补丁未生效。
5. **代理必须常驻。** iframe 已经指向 `127.0.0.1:5175`，代理不在时该窗口白屏。
   所以按顺序：先起代理，再启动 Devin；退出用 `uninstall.py` 还原。
6. 本目录**不收录**任何上游 bundle、缓存或厂商资源，只收录本项目自己的代码与译文。

## 命名与术语

与 `translations/` 保持同一套口径：Extension=扩展、Agent=智能体、Session=会话、
Prompt=提示词、Approval=审批、Workspace=工作区、Sandbox=沙箱、quota=额度、
rate limit=速率限制。`Devin` / `Copilot` / `VS Code` / `Claude` / `MCP` / `API` / `CLI`
等保持原文；`{{product}}`、`<br />` 等占位符原样保留。
