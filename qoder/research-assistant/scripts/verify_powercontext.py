"""Verify the embedded ASGI-transport PowerContext path works end to end."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from pc_runtime import embedded_powercontext  # noqa: E402
from powercontext.http import (  # noqa: E402
    CreateScopeRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
)

OUT = Path(__file__).resolve().parent / ".demo-pc"


async def main() -> None:
    import shutil

    shutil.rmtree(OUT, ignore_errors=True)
    async with embedded_powercontext(OUT) as client:
        caps = await client.get_capabilities()
        print(f"[OK] capabilities search_modes={caps.search_modes}")
        scope = await client.create_scope(
            CreateScopeRequest(
                title="user1 文献偏好",
                summary="保存用户研究偏好用于推荐",
                idempotency_key="verify-scope-user1",
            )
        )
        print(f"[OK] scope_id={scope.scope_id}")
        await client.remember_memory(
            RememberMemoryRequest(
                scope_id=scope.scope_id,
                kind="preference",
                text="用户偏好标签: 深度学习, NLP, Transformer",
                reason="保存用户研究偏好",
            )
        )
        print("[OK] memory saved")
        hits = await client.search_memory(
            SearchMemoryRequest(scope_id=scope.scope_id, query="偏好", mode="fts")
        )
        print(f"[OK] recalled {len(hits.hits)} hit(s)")
        for h in hits.hits:
            print("     -", h.text)
        assert hits.hits, "expected at least one recalled memory"
    print("[DONE] embedded PowerContext verified")


if __name__ == "__main__":
    asyncio.run(main())
