# 账本先生：会记仇的 NPC

一个用 Dify 编排、用 PowerContext 记住玩家每一笔烂账的互动小游戏。

你在村口遇到一只活了三百年的老山羊。它摆摊记账，说话客气，但你说的每句话、干过的每件坏事都会
写进账本。下次再来——哪怕换了新会话、重启了服务——它仍然会翻出旧账，阴阳怪气地跟你清算。

## 1. 玩法与技术分工

| 环节 | 由谁承担 | 具体做什么 |
| --- | --- | --- |
| 输入接收、流程编排 | Dify（Chatflow） | 开始节点收玩家名字与发言，串起检索、模型生成、记忆写回、回答 |
| 旧账召回 | Dify HTTP Request 节点 → PowerContext `/v1/context/prepare` | 用玩家当前这句话检索该账本的长期记忆 |
| 角色扮演 | Dify LLM 节点 | 按人设把召回结果揉进台词，必须点出具体旧账细节 |
| 记账写回 | Dify HTTP Request 节点 → PowerContext `/v1/memory/remember` | 把这一轮"玩家说了什么、我怎么回的"写成一条新账 |
| 长期记忆存储与复用 | PowerContext | 按 scope 持久化记忆条目，提供跨会话、跨进程的召回 |

Dify 自己的会话变量只在单个会话内有效；这里刻意关掉了会话记忆（LLM 节点不启用 memory window），
所有"记得你"的效果都来自 PowerContext 的跨会话召回。断开 PowerContext 后，NPC 会变成第一次见你。

## 2. 目录与文件用途

| 文件 | 用途 |
| --- | --- |
| `dify/dsl/grudge-npc.yml` | Chatflow DSL，包含全部 7 个节点，直接导入 Dify |
| `dify/scripts/init_powercontext.py` | 创建固定 scope 并写入初始旧账，打印需要填进 DSL 的 `scope_id` |
| `dify/scripts/inspect_memory.py` | 查看某个 scope 的召回结果，用于验证与取证 |
| `dify/samples/verification.md` | 可逐步执行的验证样例与预期表现 |

导入顺序：先 `init_powercontext.py` 拿到 `scope_id`，再开内网穿透，再导入 DSL，最后把穿透地址和
`scope_id` 填进 DSL 的两个 HTTP 节点。

## 3. 运行环境

| 组件 | 版本与说明 |
| --- | --- |
| Dify | Dify 云版（`https://cloud.dify.ai`），无需本地 Docker。DSL 版本 `0.1.5`，导入时由 Dify 自动升级 |
| PowerContext | `oceanbase/powercontext` 仓库 `2026-competition` 分支；Python 3.11+ 与 `uv`；默认 SQLite，无需额外数据库 |
| 内网穿透 | `cloudflared` 快速隧道，把本地 `127.0.0.1:8000` 映射为公网 HTTPS，供 Dify 云版调用 |
| 模型 | DSL 默认 `langgenius/openai/openai` + `gpt-4o-mini`；也可按 4.5 换成 OpenAI-API-compatible 插件（DeepSeek、通义等） |
| 资源 | 本机只需跑一个 Python 服务和一条隧道，内存占用很小 |

## 4. 部署与运行

以 Windows PowerShell 为例，Linux/macOS 把 `$env:X = "y"` 换成 `export X=y` 即可。

### 4.1 启动 PowerContext

```powershell
uv tool install --force "powercontext[cli,server] @ git+https://github.com/oceanbase/powercontext.git@2026-competition"
powercontext server run
```

默认监听 `127.0.0.1:8000`，数据落在 `POWERCONTEXT_HOME`。要从零开始演示，停掉服务、清空该目录再重启。

验证：

```powershell
curl.exe --silent http://127.0.0.1:8000/health/live
# {"status":"ok"}
```

### 4.2 初始化账本

```powershell
python dify/scripts/init_powercontext.py
```

输出示例：

```
scope_id = scp_75hg49ejkr7yjfw8z8n839vttg
写入旧账[decision] 玩家在集市上拿走账本先生一枚铜币，没有付钱。
写入旧账[decision] 玩家掀翻了账本先生的摊位，番茄滚了一地，还说老山羊算不清账。
写入旧账[fact] 玩家欠账本先生三文钱，说下次一起还，至今没还。
```

记下这个 `scope_id`。脚本可重复执行：scope 已存在时不会重复写初始旧账。

### 4.3 开内网穿透

下载 `cloudflared`（免安装，单文件）：

```powershell
winget install --id Cloudflare.cloudflared
```

或直接从 GitHub 下载：

```powershell
curl.exe -L -o cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
```

启动快速隧道（保持这个窗口开着）：

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

终端里会打印形如 `https://xxxx-yyyy.trycloudflare.com` 的地址。验证公网可访问：

```powershell
curl.exe --silent https://xxxx-yyyy.trycloudflare.com/health/live
# {"status":"ok"}
```

注意：快速隧道每次重启都会换域名，换完需要回 Dify 改两个 HTTP 节点的 URL。

### 4.4 导入 DSL 到 Dify 云版

1. 登录 `https://cloud.dify.ai`，进入「工作室」。
2. 右上角「创建空白应用」旁的下拉 → **导入 DSL 文件** → 选择 `dify/dsl/grudge-npc.yml`。
3. 打开「召回旧账」节点，改两处：
   - `scope_id` 的值 → 4.2 输出的 ID
   - URL → `https://xxxx-yyyy.trycloudflare.com/v1/context/prepare`
4. 打开「记下新账」节点，改两处：
   - `scope_id` 的值 → 同上
   - URL → `https://xxxx-yyyy.trycloudflare.com/v1/memory/remember`
5. 确认 LLM 节点的模型可用（云版需先在自己的工作区配置模型供应商，见 4.5）。
6. 右上角「运行」，在聊天框开始对话。

### 4.5 配置或更换模型

- 有 OpenAI Key：在「设置 → 模型供应商」里填入 Key，DSL 默认的 `gpt-4o-mini` 即可直接用。
- 没有 OpenAI Key：安装 **OpenAI-API-compatible** 插件，填入 DeepSeek / 通义等服务的 Base URL 与 Key，
  然后打开 LLM 节点把模型换成对应模型。节点里的提示词不需要改动。

## 5. 体验方式

一轮对话固定为：召回旧账 → 生成台词 → 写回新账。建议按以下顺序体验：

1. 第一轮：「我只是路过，别记我」——它会把初始三条旧账里的事翻出来。
2. 第二轮：「我把你的铜币还你了」——它会顺着上一轮继续算账。
3. 新开会话（或重启应用、重启 PowerContext 后再聊）问「你还记得我吗？」——旧账仍在，
   这就是 PowerContext 在实际起作用的地方。

完整可复现样例见 `dify/samples/verification.md`。

## 6. 已知限制

- 快速隧道域名是临时的，重启即变；演示和截图时保持隧道窗口不关。
- 隧道把本地服务暴露到公网且 PowerContext 未开鉴权，仅用于演示，用完即关；不要把数据目录中的真实隐私写入。
- 最小 Server 使用全文检索：中文按整句片段匹配，问句过短（如单个虚词）可能召回为空，此时 NPC 会当作新账处理，属预期行为。
  需要语义检索时按 PowerContext 文档配置 embedding 与向量检索。
- 账本按 `scope_id` 隔离，当前只有一个共享账本；多人玩法需要按玩家分配 scope。
- `scope_id` 与隧道域名在 DSL 里是手填常量，换一次要改两个节点。

## 7. 来源与许可

- 未复用第三方 DSL 或代码；工作流为本作品原创。
- PowerContext 采用 Apache-2.0，与主仓库一致。
- 应用图标使用 emoji，无外部素材。
