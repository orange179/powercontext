"""查看指定 scope 的召回结果，用于验证样例中记录记忆读写证据。

用法：

    python dify/scripts/inspect_memory.py <scope_id> [查询词]

输出 prepared context 的状态与条目，可直接截图或粘贴进验证记录。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

BASE_URL = os.environ.get("POWERCONTEXT_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("POWERCONTEXT_TOKEN")


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


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    scope_id = argv[1]
    query = argv[2] if len(argv) > 2 else "旧账"
    result = post("/v1/context/prepare", {"scope_id": scope_id, "query": query})

    print(f"query = {query}")
    print(f"status = {result.get('status')}")
    content = result.get("content") or ""
    print("---- prepared content ----")
    print(content)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
