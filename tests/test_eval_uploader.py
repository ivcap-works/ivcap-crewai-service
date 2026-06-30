"""
Tests for eval_uploader.py (evaluation record building + upload).

These tests use lightweight fakes for the crew result, request, and LLM objects
so they assert on the record shape and the upload behaviour without any
network/auth or dependence on real crewai/ivcap internals.

Covers:
  - job_entity_urn()     bare id -> job URN (idempotent)
  - build_eval_record()  pure record assembly
  - upload_eval_record() upload record as a JSON artifact, then link it to the job
                         via an aspect (fire-and-forget, swallows exceptions)
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Must set env vars before importing any crewai / ivcap modules.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("IVCAP_BASE_URL", "http://localhost:8077")
os.environ.setdefault("IVCAP_SERVICE_ID", "urn:ivcap:service:test-service")

# Ensure project root is on sys.path so imports resolve correctly.
sys.path.insert(0, str(Path(__file__).parent.parent))

import eval_uploader
from eval_uploader import (
    EVAL_RECORD_SCHEMA,
    build_eval_record,
    job_entity_urn,
    upload_eval_record,
)


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _fake_task_output(name, agent, raw, description="desc", summary="sum"):
    return SimpleNamespace(
        name=name, agent=agent, raw=raw, description=description, summary=summary
    )


@pytest.fixture
def crew_result():
    return SimpleNamespace(
        raw="Final answer.",
        tasks_output=[
            _fake_task_output("research", "Researcher", "research output"),
            _fake_task_output("write", "Writer", "write output"),
        ],
        token_usage=SimpleNamespace(
            total_tokens=1000,
            prompt_tokens=700,
            completion_tokens=300,
            cached_prompt_tokens=120,
            successful_requests=5,
        ),
    )


@pytest.fixture
def req():
    return SimpleNamespace(
        name="my_crew",
        crew_ref="urn:ivcap:aspect:crew-def",
        inputs={"research_topic": "What is X?", "additional_inputs": "prior notes"},
    )


@pytest.fixture
def llm():
    return SimpleNamespace(model="gpt-4.1", temperature=0.7)


@pytest.fixture
def record(req, crew_result, llm):
    return build_eval_record(
        req=req,
        crew_result=crew_result,
        llm=llm,
        planning_llm=SimpleNamespace(model="gpt-4.1"),
        run_time_sec=12.5,
        process_time_sec=1.2,
        job_id="1234abcd",
    )


# ---------------------------------------------------------------------------
# job_entity_urn()
# ---------------------------------------------------------------------------


def test_job_entity_urn_from_bare_id():
    assert job_entity_urn("1234abcd") == "urn:ivcap:job:1234abcd"


def test_job_entity_urn_idempotent():
    full = "urn:ivcap:job:1234abcd"
    assert job_entity_urn(full) == full


# ---------------------------------------------------------------------------
# build_eval_record()
# ---------------------------------------------------------------------------


def test_record_top_level_shape(record):
    assert record["$schema"] == EVAL_RECORD_SCHEMA
    for key in ("service_id", "job_id", "crew_ref", "inputs", "result", "metrics", "llm"):
        assert key in record
    assert record["job_id"] == "urn:ivcap:job:1234abcd"
    assert record["service_id"] == "urn:ivcap:service:test-service"
    assert record["crew_ref"] == "urn:ivcap:aspect:crew-def"
    # Dropped fields must not be present.
    for absent in ("service_version", "crew_name", "created_at"):
        assert absent not in record


def test_inputs_block(record):
    assert record["inputs"]["query"] == "What is X?"
    assert record["inputs"]["additional_inputs"] == "prior notes"


def test_result_block(record):
    assert record["result"]["answer"] == "Final answer."
    tasks = record["result"]["task_outputs"]
    assert len(tasks) == 2
    assert tasks[0] == {
        "order": 1,
        "name": "research",
        "agent": "Researcher",
        "description": "desc",
        "summary": "sum",
        "raw": "research output",
    }
    assert tasks[1]["order"] == 2


def test_metrics_block(record):
    m = record["metrics"]
    assert m["total_tokens"] == 1000
    assert m["prompt_tokens"] == 700
    assert m["completion_tokens"] == 300
    assert m["cached_prompt_tokens"] == 120
    assert m["successful_requests"] == 5
    assert m["run_time_sec"] == 12.5
    assert m["process_time_sec"] == 1.2


def test_llm_block(record):
    llm_block = record["llm"]
    assert llm_block["model"] == "gpt-4.1"
    assert llm_block["planning_model"] == "gpt-4.1"
    assert llm_block["temperature"] == 0.7


def test_missing_token_usage_is_zeroed(req, llm):
    cr = SimpleNamespace(raw="x", tasks_output=[], token_usage=None)
    rec = build_eval_record(
        req=req,
        crew_result=cr,
        llm=llm,
        planning_llm=None,
        run_time_sec=0,
        process_time_sec=0,
        job_id="x",
    )
    assert rec["metrics"]["total_tokens"] == 0
    assert rec["result"]["task_outputs"] == []


def test_record_is_json_serializable(record):
    # The record is uploaded as a JSON artifact, so it must round-trip cleanly.
    assert json.loads(json.dumps(record)) == record


# ---------------------------------------------------------------------------
# upload_eval_record()  (artifact -> aspect)
# ---------------------------------------------------------------------------


def _fake_ivcap_with_artifact(artifact_id="urn:ivcap:artifact:xyz"):
    ivcap = MagicMock()
    ivcap.upload_artifact.return_value = SimpleNamespace(id=artifact_id)
    return ivcap


def test_upload_uploads_artifact_then_links_aspect(record):
    ivcap = _fake_ivcap_with_artifact()
    asyncio.run(upload_eval_record(None, "1234abcd", record, ivcap=ivcap))

    # 1) record uploaded as a JSON artifact
    ivcap.upload_artifact.assert_called_once()
    _, up_kwargs = ivcap.upload_artifact.call_args
    assert up_kwargs["name"] == "eval-record-1234abcd.json"
    assert up_kwargs["content_type"] == "application/json"
    body = json.loads(up_kwargs["io_stream"].read().decode("utf-8"))
    assert body == record

    # 2) aspect on the job URN references the artifact
    ivcap.add_aspect.assert_called_once()
    args, asp_kwargs = ivcap.add_aspect.call_args
    assert args[0] == "urn:ivcap:job:1234abcd"
    assert args[1] == {"artifactUrn": "urn:ivcap:artifact:xyz"}
    assert asp_kwargs["schema"] == EVAL_RECORD_SCHEMA
    assert "policy" not in asp_kwargs  # default (private)


def test_upload_swallows_exceptions(record):
    ivcap = MagicMock()
    ivcap.upload_artifact.side_effect = RuntimeError("boom")
    # Must not raise.
    asyncio.run(upload_eval_record(None, "1234abcd", record, ivcap=ivcap))
    ivcap.upload_artifact.assert_called_once()
    ivcap.add_aspect.assert_not_called()


def test_upload_skips_without_token(record):
    # No injected client and no JWT -> must skip without building a client/raising.
    asyncio.run(upload_eval_record(None, "1234abcd", record))


def test_upload_builds_authenticated_client(record, monkeypatch):
    monkeypatch.delenv("IVCAP_URL", raising=False)
    monkeypatch.setenv("IVCAP_BASE_URL", "https://develop.ivcap.net")
    captured = {}

    class FakeIVCAP:
        def __init__(self, url=None, token=None):
            captured["url"] = url
            captured["token"] = token

        def upload_artifact(self, **kwargs):
            captured["uploaded"] = True
            return SimpleNamespace(id="urn:ivcap:artifact:xyz")

        def add_aspect(self, *args, **kwargs):
            captured["linked"] = args[1]

    monkeypatch.setattr(eval_uploader, "IVCAP", FakeIVCAP)
    asyncio.run(upload_eval_record("jwt-123", "1234abcd", record))

    assert captured["token"] == "jwt-123"
    assert captured["url"] == "https://develop.ivcap.net"
    assert captured.get("uploaded") is True
    assert captured["linked"] == {"artifactUrn": "urn:ivcap:artifact:xyz"}
