# Devin Web 应用简中覆盖层（webapp overlay）

这个目录处理的是**语言包问不到的三层界面**。它们需要两种彼此独立的机制：

| 层 | 出现在哪里 | 机制 | 需要常驻代理？ |
| --- | --- | --- | --- |
| **1** | 远程渲染的 Sessions / Settings 网页 | 改写 bundle 里的 iframe 基址指向本地反向代理，由代理逐条替换字符串 | **是** |
| **2** | 随安装包发布的 chat 前端**自带**的英文目录（导航栏、本地设置页、部分面板） | 直接对本地 bundle 做字节级 `en → zh` 键值对替换 | **否** |

两层共用同一份译源（`dict-zh.json`），但**匹配对象完全不同**、互不影响：
第 1 层匹配的是"从上游抓回来的分片"，第 2 层匹配的是"安装树里已经躺着的目录"。
第 2 层是**本地文件直改** —— 改完即生效、无进程、无网络依赖，比常驻代理稳得多。

---

## 第 1 层：远程渲染的网页

Devin Desktop 的 **Sessions / Settings** 界面不是 IDE 本地渲染的，而是把
`https://app.devin.ai` 装进一个沙箱 iframe 里远程渲染。因此
`translations/` 里的 VS Code 语言包**结构上无法**覆盖它 —— 那些字符串不在
nls 键表里，加多少条都不会生效。

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

## 第 2 层：本地自带的英文目录

第 1 层只覆盖远程网页。但 Devin 的 chat 前端**在安装树里自带一份完整的英文
i18n 目录**，它才是导航栏、本地设置页这些"壳内"文案的来源：

```js
// out/vs/workbench/windsurf-chat-client/index.js
Ua.use(UW).init({
  resources: { en: { translation: jr } },
  lng: "en", fallbackLng: "en",
  ns: ["translation", "review"], defaultNS: "translation",
})
```

`jr` 是一张 `{"camelCaseKey":"English"}` 的嵌套大表（同一份目录也被内联进
`out/vs/sessions/sessions.desktop.main.js`）。它**不接受外部注入** —— 上游只带
en / ja / es / pt 四种语言，`lng` 与 `fallbackLng` 都写死 `"en"`，语言包的
`translationsConfigFile` 注入点只赋了值却从不被消费。所以这里只能在字节层把目录本身换掉。

做法是在 `<key>":"<English>"` 这个**带键名的完整配对**上做替换。键是唯一标识符，
因此配对替换不会误伤同名的遥测事件标识符或普通代码 —— 与 `translations/` 里
nls 键的替换策略是同一套标准。

### 为什么这是安全的

下面四条都由独立脚本逐字节核验（见「自测」），不是推断：

- **键值对精确配对**，且 `en == zh` 的键（`Devin Desktop`、`Wiki` 等品牌名）
  根本不生成编辑，不会有半截替换。
- **纯 ASCII 输出**：中文按 `\uXXXX` 转义写入（上游自带的日文副本就是转义形式），
  被编辑的字节区间只含 ASCII。实测三个 bundle 里，替换**一个非 ASCII 字节都没引入**
  （`sessions` / `workbench` 的出厂镜像本身就含 15 个非 ASCII 字节，那是上游的；
  `windsurf-chat-client` 出厂是纯 ASCII，改完仍是 0 个）。
- **幂等**：把编辑集重跑一遍，命中数恒为 `0` —— 不存在"某个 pattern 能匹配到
  别的替换串造出的文本"这类顺序性问题。
- **可逆**：改动的文件都留 `.zh-orig` 备份，且备份**只在文件仍是出厂态时才刷新**。
  无条件刷新会把"已打补丁"存成"原版"，卸载就回不到出厂态了。

### 当前覆盖度（实测）

```
catalogue : 32 / 41 keys landed, 96 occurrences
            (9 dictionary key(s) absent from this bundle)
```

- **96 次替换**分布在 **32 个字典键**上、由 **41 个 pattern** 表达 —— 一个键可能需要
  多个 pattern，因为同一个英文词在不同位置拼写不同。目录在 bundle 里被**重复内联**，
  所以单个键会落地多次（仅 `"review"` 一个键就落了 29 次）。
- 计数单位是**字典键**而不是 pattern：靠"替换串在不在"反推，会让同一键的多种拼法
  一起被记为命中（曾因此虚报成 `35 / 41`）。现在 `--status` 与安装输出同口径。
- 9 个键**不在这两个 bundle 的目录里** —— `groupSettings`、`dataRetention`、
  `navigateBack` / `navigateForward` / `navigateHome`、`botsRailSessions`、
  `allowDataRetention` / `allowDataRetentionDescription`，以及 `localSettings`。
  前八个属于远程那一片，由第 1 层负责。
- `localSettings` 是**对象**而非字符串（`"localSettings":{"sections":{...}}`），
  没有字符串配对可换 —— 它的 15 个叶子键（General / Plan information / Extensions /
  Agents / Devin Local / Configuration / Customizations / Models / Authentication /
  Editor / User interface / Devin Tab / Shortcuts / Lifeguard / Advanced）需要另做
  上下文限定的定向替换，尚未实现。

## 文件

| 文件 | 作用 |
| --- | --- |
| `proxy.mjs` | 零依赖反向代理。回环专用，缓存上游原文，服务时做字符串替换（**第 1 层**） |
| `dict-zh.json` | **人工译源**（唯一需要手改的文件）。两层的词表都从这里构建 |
| `zh-hans.json` | 构建产物，代理实际读取的词表。`{ key: { en, zh } }` |
| `install.py` | 字节级补丁：① **第 1 层** —— 改写 2 个 bundle 的 iframe 基址（合计 4 处）；② **第 2 层** —— 替换另外 2 个 bundle 自带目录里的 `en → zh` 配对。两者都同步 `product.json` 校验值 |
| `uninstall.py` | 从 `.zh-orig` 备份还原全部 3 个 bundle，再按还原结果**重算** `product.json` 校验值 |
| `warmup-all.mjs` | 闭包式预热：把整个 Vite 资源图抓进缓存（**只有第 1 层需要**） |
| `make-fixture.mjs` / `test-proxy.mjs` | 代理的离线自测：夹具生成 + 行为校验（完全不联网） |
| `test-install.py` | 安装器的离线自测：合成应用树 + 打补丁/还原/可复现校验（完全不联网、不需要装 Devin） |

## 用法

```bash
# 1（第 1 层专用）. 启动覆盖层代理（回环，常驻）
node webapp/proxy.mjs --port 5175

# 2（第 1 层专用）. 首次把资源图抓进缓存（约 1,830 个分片，~9 MB）
node webapp/warmup-all.mjs --port 5175

# 3. 打补丁（两层一起；Devin 可以开着，重启后生效）
python webapp/install.py --port 5175

# 4. 查看状态 / 还原
python webapp/install.py --status
python webapp/uninstall.py
```

**第 2 层不需要第 1、2 步** —— 它只改本地文件。所以即使代理没起、缓存为空，
本地目录那部分（导航栏、本地设置页）也应当显示中文；代理只决定远程网页那部分。

配套的 Windows 启动器在仓库之外，会按顺序做「起代理 → 打补丁 → 启动 Devin」。

### 补丁到底改了什么

**第 1 层**：共 **4 处**调用点（分布在 2 个 bundle），把 iframe 基址从一个运行时
计算值换成本地字面量：

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

**第 2 层**：在 `windsurf-chat-client/index.js` 与 `sessions.desktop.main.js` 里，
把目录的 `en` 值逐个换成 `zh`：

```diff
- "automations":"Automations"
+ "automations":"\u81ea\u52a8\u5316"
```

中文按 `\uXXXX` 转义写回，被编辑的字节区间因此只含 ASCII。原文里以 `'` 出现的
（目录嵌在单引号 JS 字符串里）会同时尝试 `\'` 这一种拼法。

`resources/app/product.json` 里的 `checksums` 表覆盖了 **三个** bundle
（`vs/sessions/sessions.desktop.main.js`、`vs/workbench/workbench.desktop.main.js`、
`vs/workbench/windsurf-chat-client/index.js`）。改完 bundle 必须同步改对应项，
否则完整性校验会把安装判为损坏：

```python
base64(SHA-256(file))            # 去掉尾部 '=' 填充
```

`install.py` / `uninstall.py` 会自动维护它。`product.json` **不做文件级备份**：
卸载时按**还原后的 bundle 重算**该表 —— 若改成备份文件，第二次编辑就会把
「半打补丁」的中间态存成"原版"，还原后表与 bundle 不符。写入前先把原文读进
内存，校验失败即从内存回滚。

状态文件里的 `original_checksums` 记的是**出厂镜像的摘要**，而它取自 `.zh-orig`
备份而不是 `product.json`：`product.json` 在非首次安装时已经是打过补丁的值，
照抄它只会记下"文件当时碰巧的哈希"，对卸载毫无意义。备份即出厂镜像，是唯一权威。

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
| `/__zh/recent` | 最近 80 条**被代理的实际请求**（method + 路径，**去查询串**、不含任何头部） |

```bash
curl -s http://127.0.0.1:5175/__zh/health
curl -s http://127.0.0.1:5175/__zh/keys
curl -s http://127.0.0.1:5175/__zh/recent
```

**计数口径**：`stats.requests` 只统计**其它进程**发来的请求。`/__zh/*` 诊断端点
是本进程自己的，另计为 `stats.diag` —— 否则一次 `health` 轮询就能把
`requests` 推高，造成「Devin 正在使用代理」的假象。

回答「Devin 到底有没有调用代理」只用两个不自我污染的指标：
`stats.requests`（应为 0 或在 Devin 启动后跳增）与 `/__zh/recent` 的路径列表。

`/__zh/keys` 读的是**缓存里的上游原文**，不是改写后的结果，因此报告不会被自己的
替换结果污染 —— 这是缓存必须存原文、只有服务时才改写的原因。

第 2 层**不经过代理**，所以它不会出现在任何 `/__zh/*` 计数里。它的状态只有一个入口：
`install.py --status`（`catalogue : N keys landed` 与 `original : 0 left`）。
反过来说，`--status` 全绿也**只证明文件被改了**，不证明界面渲染出来就是中文 ——
那一层要看 `/__zh/health` 的 `stats.requests`，它长期为 0 就说明远程那部分没走代理。

## 自测

两套都**完全不联网**，可在提交前随时跑。

### 1. 安装器（两层一起）

```bash
python webapp/test-install.py
```

自建一棵合成应用树再打补丁，不碰任何真实安装，因此不需要装 Devin。
断言覆盖的都是容易悄悄坏掉的地方：

- 在**两份目录副本里重复出现**的键 → 两次都要换到
- 需要**两种英文拼法**的键（字典原文 + 别名）→ 两种都要换到
- `en == zh` 的键（`Wiki`、`Devin Desktop`）→ **一个编辑都不能产生**
- 带 `{{product}}` 占位符的译文 → 占位符必须原样保留
- `localSettings` → 只要字符串配对**在场**就能换（真实 bundle 只是没有这一对）
- PR-review 诱饵 `oSe(this.devinService.webUrl,`（**无下划线**，紧邻被改的那一处）
  → **绝不能被改写**
- **字节增量 == 逐次替换长度差之和** → 任何落在 pattern 之外的杂散改动都会被抓出
- 纯 ASCII 不变、`product.json` 校验值同步
- install → uninstall → install：与出厂**逐字节相同**且可复现

状态文件被重定向到临时 `LOCALAPPDATA`，所以测试不会污染真实安装记录的出厂摘要。

### 2. 代理

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
   （它会刷新 `.zh-orig` 备份，避免用旧构建回滚）。`install.py` 会把出厂摘要
   记进状态文件，卸载时与还原结果比对；不一致说明 Devin 升过级 ——
   这是预期情况，不是错误。
4. **补丁按版本失效：换版本必须重跑 `install.py`。** 基址字面量的上下文
   （`V6r(But(...))` / `oSe(QC(...))`）若被上游改写，`--status` 会报
   `original : N left` 且校验值不匹配，据此即可判定补丁未生效。
5. **常驻代理只有第 1 层需要。** iframe 已经指向 `127.0.0.1:5175`，代理不在时
   远程网页那一块会白屏；但**第 2 层是本地文件直改，不依赖代理** ——
   即使代理没起，本地目录那部分（导航栏、本地设置页）也应当显示中文。
   判断"代理到底有没有被用上"不能用 `stats.requests` 之外的间接证据（见「诊断」）。
6. **第 2 层覆盖不了远程那一片。** 两个词表同源，但匹配对象不同：只出现在远程
   分片里的键（如 `Data retention`）必须靠第 1 层；反过来，只出现在本地目录里的
   键即使代理起了也不会被第 1 层碰到。
7. 本目录**不收录**任何上游 bundle、缓存或厂商资源，只收录本项目自己的代码与译文。

## 命名与术语

与 `translations/` 保持同一套口径：Extension=扩展、Agent=智能体、Session=会话、
Prompt=提示词、Approval=审批、Workspace=工作区、Sandbox=沙箱、quota=额度、
rate limit=速率限制。`Devin` / `Copilot` / `VS Code` / `Claude` / `MCP` / `API` / `CLI`
等保持原文；`{{product}}`、`<br />` 等占位符原样保留。
