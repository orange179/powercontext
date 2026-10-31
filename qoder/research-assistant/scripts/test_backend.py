"""End-to-end test of the real backend using a real embedded PowerContext."""

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("RESEARCH_ASSISTANT_DATA_DIR", tempfile.mkdtemp(prefix="ra-e2e-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

CSV = Path(__file__).resolve().parent.parent / "data" / "sample_papers.csv"


def run() -> None:
    csv_text = CSV.read_text(encoding="utf-8")
    with TestClient(main.app) as client:
        # 前端以 JSON 字符串提交 CSV，这里完全模拟前端请求。
        r = client.post("/api/documents/import", content=json.dumps(csv_text), headers={"Content-Type": "application/json"})
        print("[import]", r.status_code, "imported=", len(r.json()))
        assert r.status_code == 200 and len(r.json()) >= 5

        r = client.get("/api/documents")
        print("[documents]", r.status_code, "count=", len(r.json()))
        assert r.status_code == 200 and len(r.json()) >= 5

        r = client.post("/api/search", json={"query": "NLP", "top_k": 5})
        results = r.json()
        print("[search]", r.status_code, "hits=", len(results))
        for item in results:
            print("   -", item["document"]["title"], round(item["score"], 3))
        assert r.status_code == 200 and results, "search must return PowerContext hits"

        r = client.post(
            "/api/user/user1/preferences",
            json={"user_id": "user1", "preferred_tags": ["NLP", "Transformer"], "reading_progress": {}, "search_history": []},
        )
        print("[save prefs]", r.status_code, r.json())
        assert r.status_code == 200

        r = client.get("/api/user/user1/preferences")
        print("[recall prefs]", r.status_code, r.json())
        assert r.status_code == 200 and r.json()["preferred_tags"], "prefs must be recalled from PowerContext"

        r = client.get("/api/user/user1/recommendations")
        payload = r.json()
        print("[recommendations]", r.status_code, [d["document"]["title"] for d in payload["recommendations"]])
        assert r.status_code == 200 and payload["recommendations"], "preferences must drive recommendations"

        r = client.get("/health")
        print("[health]", r.status_code, r.json())
        assert r.status_code == 200 and r.json()["tech"] == "PowerContext"

    print("[DONE] backend + PowerContext end-to-end OK")


if __name__ == "__main__":
    run()
