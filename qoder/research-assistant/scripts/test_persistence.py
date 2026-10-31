"""验证「重启后数据与记忆仍可读回和复用」。

两段会话使用同一个数据目录：
  会话 1：导入 7 篇文献 -> 检索 NLP -> 保存偏好 -> 退出（关闭 PowerContext）
  会话 2：重新启动应用（重新打开同一个 SQLite）-> 读回文献列表、检索结果、偏好，并生成推荐
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(tempfile.mkdtemp(prefix="ra-persist-"))
os.environ["RESEARCH_ASSISTANT_DATA_DIR"] = str(DATA_DIR)
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

CSV_TEXT = (ROOT / "data" / "sample_papers.csv").read_text(encoding="utf-8")


def check(label: str, condition: bool, detail: str) -> None:
    print(f"[{'OK ' if condition else 'FAIL'}] {label}: {detail}")
    if not condition:
        raise SystemExit(1)


print(f"data dir: {DATA_DIR}")

# ---------------- 会话 1：写入 ----------------
with TestClient(main.app) as client:
    imported = client.post("/api/documents/import", json=CSV_TEXT).json()
    check("import", len(imported) == 7, f"{len(imported)} papers")

    hits = client.post("/api/search", json={"query": "NLP"}).json()
    check("search", len(hits) == 3, f"{len(hits)} hits, top={hits[0]['document']['title']}")

    saved = client.post("/api/user/user1/preferences", json={"preferred_tags": ["NLP", "Transformer"]}).json()
    check("save preference", saved["status"] == "ok", str(saved["memory"]))

# ---------------- 会话 2：重启后读回 ----------------
with TestClient(main.app) as client:
    docs = client.get("/api/documents").json()
    check("documents after restart", len(docs) == 7, f"{len(docs)} papers")
    check("document fields kept", docs[0]["title"] == "Attention Is All You Need" and bool(docs[0]["abstract"]),
          f"title={docs[0]['title']}, tags={docs[0]['tags']}")

    health = client.get("/health").json()
    check("health papers", health["papers"] == 7, json.dumps(health, ensure_ascii=False))

    hits = client.post("/api/search", json={"query": "NLP"}).json()
    titles = [h["document"]["title"] for h in hits]
    check("search after restart", len(hits) == 3, f"{len(hits)} hits: {titles}")

    prefs = client.get("/api/user/user1/preferences").json()
    check("preferences read back", prefs["preferred_tags"] == ["NLP", "Transformer"],
          f"{prefs['preferred_tags']} from {prefs['recalled_memories']}")

    recs = client.get("/api/user/user1/recommendations").json()
    check("recommendations reuse memory", len(recs["recommendations"]) == 3,
          f"{len(recs['recommendations'])} recs based on {recs['based_on']}")

print("[DONE] data and memory survive an application restart")
