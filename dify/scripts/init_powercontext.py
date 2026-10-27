"""初始化 PowerContext：创建固定 scope，并写入账本先生的初始旧账。

用法（PowerContext Server 已启动）：

    python dify/scripts/init_powercontext.py

成功后会把 scope_id 打印出来，需要把它填进 DSL 的两个 HTTP Request 节点
（「召回旧账」和「记下新账」）的 `scope_id` 字段。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/")
SCOPE_KEY = "grudge-npc-v1"
SCOPE_TITLE = "账本先生的账本"
TOKEN = os.environ.get("POWERCONTEXT_TOKEN")

SEED_GRUDGES = [
    ("decision", "玩家在集市上拿走账本先生一枚铜币，没有付钱。"),
    ("decision", "玩家掀翻了账本先生的摊位，番茄滚了一地，还说老山羊算不清账。"),
    ("fact", "玩家欠账本先生三文钱，说下次一起还，至今没还。"),
]


def post(path: str, payload: dict) -> dict:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def get(path: str) -> dict:
    headers = {}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(f"{BASE_URL}{path}", headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def create_scope() -> dict:
    payload = {
        "title": SCOPE_TITLE,
        "summary": "会记仇的山羊 NPC 的长期记忆",
        "idempotency_key": SCOPE_KEY,
    }
    try:
        return post("/v1/scopes", payload)
    except urllib.error.HTTPError as error:
        if error.code != 409:
            raise
        # 同一 idempotency_key 已被旧 payload 占用时，按标题找回已有 scope。
        for item in get("/v1/scopes")["items"]:
            if item.get("title") == SCOPE_TITLE:
                return item
        raise


def main() -> int:
    scope = create_scope()
    scope_id = scope["scope_id"]
    print(f"scope_id = {scope_id}")

    existing = post("/v1/context/prepare", {"scope_id": scope_id, "query": "旧账"})
    if existing.get("status") == "ready":
        print("该 scope 已有记忆，跳过初始旧账写入。")
    else:
        for kind, text in SEED_GRUDGES:
            post("/v1/memory/remember", {"scope_id": scope_id, "kind": kind, "text": text})
            print(f"写入旧账[{kind}] {text}")

    print()
    print("把下面这行填进 DSL 中「召回旧账」和「记下新账」两个 HTTP 节点的 scope_id：")
    print(f"  {scope_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
