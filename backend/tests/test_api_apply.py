"""API-level test of the human-in-the-loop endpoints (needs fastapi + httpx)."""
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_apply_endpoint_and_downloads(isolated):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.runs import store
    from backend.schemas import Result

    result = Result.model_validate(json.loads((ROOT / "frontend" / "mock" / "result.json").read_text(encoding="utf-8")))
    result.run_id = "abc123"
    store.create("abc123", {"filename": "acme_policy.txt"})
    shutil.copy(ROOT / "samples" / "sample_aml_policy.txt", store.dir("abc123") / "upload.txt")
    store.save_result(result)

    c = TestClient(app)
    assert c.post("/api/runs/abc123/apply", json={"fixes": []}).status_code == 422
    r = c.post("/api/runs/abc123/apply", json={"fixes": [{"finding_id": "F7"}, {"finding_id": "F9", "text": "7.2 Edited."}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["changes"]) == 2 and "7.2 Edited." in body["full_text"]
    d = c.get(body["docx_url"])
    assert d.status_code == 200 and d.content[:2] == b"PK"
    assert "acme_policy_revised.docx" in d.headers["content-disposition"]
    t = c.get(body["txt_url"])
    assert t.status_code == 200 and "7.2 Edited." in t.text
    assert c.get("/api/runs/..%2F/result").status_code == 404
