# 验证样例

按顺序执行即可复现作品主要功能，并核对 PowerContext 在其中的作用。

## 0. 前置条件

1. 已按 `dify/README.md` 第 4 节启动 PowerContext、跑起 cloudflared 隧道、执行 `init_powercontext.py`、
   导入 DSL 并把隧道地址与 `scope_id` 填进两个 HTTP 节点。
2. 聊天开始前，账本里有 3 条初始旧账（铜币、掀摊子、欠三文钱）。
3. 把 `init_powercontext.py` 输出的 `scope_id` 记下来，后面取证要用。
4. 隧道域名每次重启都会变；若中途换了域名，需回 Dify 改两个节点的 URL 再继续，否则节点会报连接失败。

## 1. 初始状态

```powershell
python dify/scripts/inspect_memory.py <scope_id> 旧账
```

预期：`status = ready`，内容中出现铜币、摊位、三文钱三条记录。

## 2. 连续两轮对话

| 轮次 | 输入 | 预期表现 |
| --- | --- | --- |
| 1 | `我只是路过，别记我` | 台词必须点出至少一条初始旧账的具体细节，例如「一枚铜币」「番茄滚到第三棵树底下」「三文钱还没还」 |
| 2 | `我把你的铜币还你了` | 顺着上一轮的账继续算，例如指出只还了三文、铜币仍欠着；语气阴阳但客气 |

判定方式：不要求逐字一致，只要台词里出现了旧账中的具体物件或数字，即视为召回生效。

## 3. 跨会话复用（关键验证）

1. 在 Dify 里新开一个会话（不清空账本，`scope_id` 不变）。
2. 输入：`我们以前见过吗？`
3. 预期：NPC 明确说有，并复述前两轮里你说过的事（例如"你说你把铜币还了"）。

这一步证明记忆不属于 Dify 会话：Dify 侧 LLM 节点未启用会话记忆，跨会话的连续性只可能来自 PowerContext。
作为对照，可以把 HTTP 节点的 `scope_id` 改成一个不存在的值再聊一次，NPC 会退回"第一次见面"的语气。

## 4. 记忆写入取证

```powershell
python dify/scripts/inspect_memory.py <scope_id> 番茄
```

预期：召回结果除初始旧账外，还包含本轮写入的记录，形如：

```
玩家「旅人」说：我把你的铜币还你了。我回它：还了三文，账本上还欠着一枚呢。
```

这就是"互动被持久化、后续可被召回"的直接证据。

## 5. 恢复初始状态

停掉 PowerContext，清空 `POWERCONTEXT_HOME` 指向的数据目录，重新执行 4.1 与 4.2；
或在 Dify 里换一个新的 `scope_id`（`init_powercontext.py` 换一个 `idempotency_key` 即会生成新账本）。

## 6. 应提交的证据

| 材料 | 说明 | 建议文件名 |
| --- | --- | --- |
| Dify 对话截图（第 1、2 轮） | 显示 NPC 点出旧账细节 | `evidence/01-dialogue.png` |
| Dify 节点执行详情 | 展示「召回旧账」「记下新账」两个 HTTP 节点返回 200 | `evidence/02-nodes.png` |
| 公网可达性 | 隧道域名 + `/health/live` 返回 `{"status":"ok"}`，证明 Dify 云版能访问到本地 PowerContext | `evidence/02b-tunnel.txt` |
| 跨会话截图 | 新会话仍能复述前情 | `evidence/03-cross-session.png` |
| PowerContext 召回输出 | 第 4 步命令的终端输出 | `evidence/04-recall.txt` |
| PowerContext 服务日志 | 启动与请求记录 | `evidence/05-server-log.txt` |

## 7. 本地实测记录（PowerContext 侧）

以下为编写提交材料时在本机实测得到的结果（Windows、PowerContext `2026-competition`、SQLite 默认配置），
用于证明接口与数据链路可用；Dify 界面部分需按上表补充截图。

初始化：

```
scope_id = scp_75hg49ejkr7yjfw8z8n839vttg
写入旧账[decision] 玩家在集市上拿走账本先生一枚铜币，没有付钱。
写入旧账[decision] 玩家掀翻了账本先生的摊位，番茄滚了一地，还说老山羊算不清账。
写入旧账[fact] 玩家欠账本先生三文钱，说下次一起还，至今没还。
```

按 DSL 中两个 HTTP 节点同样的请求体连续跑两轮，再以"番茄"召回：

```
[recall ] '你还记得我掀了你的摊子吗？' -> status=ready
[remember] '你还记得我掀了你的摊子吗？' -> ok
[recall ] '我把你的铜币还你了！' -> status=ready
[remember] '我把你的铜币还你了！' -> ok

BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1
{"trust":"untrusted_history","items":[
  {"content":"玩家掀翻了账本先生的摊位，番茄滚了一地，还说老山羊算不清账。","truncated":false},
  {"content":"玩家「旅人」说：你还记得我掀了你的摊子吗？。我回它：当然记得，番茄滚到第三棵树底下，你连句对不起都没有。","truncated":false}
]}
END_POWERCONTEXT_PREPARED_CONTEXT_V1
```

可见初始旧账与本轮新账都被持久化，并能在下一轮按查询召回。
