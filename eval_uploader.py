"""
Evaluation Record Uploader for IVCAP CrewAI Service

After a crew run, this module assembles a self-contained "evaluation record" and
publishes it as an IVCAP aspect so a separate evaluation service can score the run
asynchronously (it queries aspects by the record's schema URN).

Design: see design/EVAL_UPLOAD_DESIGN.md

Two independently-testable pieces live here:
  - build_eval_record()  pure function: in-memory run objects -> record dict (no I/O)
  - upload_eval_record() fire-and-forget: upload the record as a JSON artifact, then
                         attach an aspect referencing it to the job (network I/O)

The record is uploaded as a JSON artifact; a reference aspect ({"artifactUrn": ...}) is
then attached to the job URN (urn:ivcap:job:{job_id}) using the default (private) policy.
"""

import asyncio
import io
import json
import os
from typing import Any, Optional

from crewai import LLM
from ivcap_client import IVCAP
from ivcap_service import getLogger

from schemas import CrewRequest

logger = getLogger(__name__)

# Schema URN the evaluation service queries on. Bump the trailing version when the
# record shape changes incompatibly.
EVAL_RECORD_SCHEMA = "urn:sd-core:schema.crewai.eval-record.1"


def job_entity_urn(job_id: str) -> str:
    """Construct the job URN from the bare job id (jobCtxt.job_id is just '1234...')."""
    if job_id and job_id.startswith("urn:ivcap:job:"):
        return job_id
    return f"urn:ivcap:job:{job_id}"


def _safe(value: Any, default: Any = None) -> Any:
    """Return value, or default if it is None / missing."""
    return default if value is None else value


def _token_usage(crew_result: Any) -> dict:
    """Extract crewai UsageMetrics into a plain dict, tolerating missing fields."""
    usage = getattr(crew_result, "token_usage", None)
    fields = (
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cached_prompt_tokens",
        "successful_requests",
    )
    out = {}
    for f in fields:
        out[f] = int(getattr(usage, f, 0) or 0) if usage is not None else 0
    return out


def _task_outputs(crew_result: Any) -> list:
    """Map crew_result.tasks_output -> ordered list of plain dicts."""
    outputs = getattr(crew_result, "tasks_output", None) or []
    records = []
    for i, to in enumerate(outputs):
        records.append(
            {
                "order": i + 1,
                "name": getattr(to, "name", None),
                "agent": getattr(to, "agent", None),
                "description": getattr(to, "description", None),
                "summary": getattr(to, "summary", None),
                "raw": _safe(getattr(to, "raw", None), ""),
            }
        )
    return records


def _inputs_block(req: CrewRequest) -> dict:
    """Build the 'inputs' block from the caller-supplied request inputs."""
    return {
        "query": req.inputs.get("research_topic"),
        "additional_inputs": req.inputs.get("additional_inputs", None),
    }


def _llm_block(llm: LLM, planning_llm: LLM) -> dict:
    """Capture the model configuration used for the run.

    Model names are read from the live LLM instances actually used for the run.
    """
    return {
        "model": getattr(llm, "model", None),
        "planning_model": getattr(planning_llm, "model", None),
        "temperature": getattr(llm, "temperature", None),
    }


def build_eval_record(
    *,
    req: CrewRequest,
    crew_result: Any,
    llm: LLM,
    planning_llm: LLM,
    run_time_sec: float,
    process_time_sec: float,
    job_id: str,
) -> dict:
    """
    Assemble the evaluation record from in-memory run objects.

    Pure function: performs no I/O and never mutates its arguments, so it is fully
    unit-testable with fabricated inputs.
    """
    return {
        "$schema": EVAL_RECORD_SCHEMA,
        "service_id": os.environ.get("IVCAP_SERVICE_ID"),
        "job_id": job_entity_urn(job_id),
        "crew_ref": req.crew_ref,
        "inputs": _inputs_block(req),
        "result": {
            "answer": crew_result.raw,
            "task_outputs": _task_outputs(crew_result),
        },
        "metrics": {
            **_token_usage(crew_result),
            "run_time_sec": run_time_sec,
            "process_time_sec": process_time_sec,
        },
        "llm": _llm_block(llm, planning_llm),
    }


def _authenticated_ivcap(jwt_token: str) -> IVCAP:
    """
    Build an IVCAP client that authenticates with the job's JWT.

    Uploading an artifact and adding an aspect are authorized writes. JobContext.ivcap
    is a bare IVCAP() which, inside the platform, is an *unauthenticated* client (no
    JWT attached), so we cannot rely on it for writes. Passing BOTH url and token forces
    the AuthenticatedClient branch in IVCAP.__init__ (supplying url keeps
    inside_platform=False), so the JWT is always attached - works in-platform and
    locally alike.
    """
    url = os.getenv("IVCAP_URL") or os.getenv("IVCAP_BASE_URL")
    return IVCAP(url=url, token=jwt_token)


def _publish_eval_record(ivcap: IVCAP, job_id: str, record: dict) -> str:
    """
    Upload the eval record as a JSON artifact, then attach an aspect to the job that
    references that artifact. Returns the artifact URN.

    Follows the platform idiom: content -> artifact, reference -> aspect. The eval
    service queries job aspects by EVAL_RECORD_SCHEMA, reads `artifactUrn`, and
    downloads the full record (`artifactUrn` is the same key download_manager uses).
    """
    data = json.dumps(record, default=str).encode("utf-8")
    artifact = ivcap.upload_artifact(
        name=f"eval-record-{job_id}.json",
        io_stream=io.BytesIO(data),
        content_type="application/json",
        content_size=len(data),
    )
    ivcap.add_aspect(
        job_entity_urn(job_id),
        {"artifactUrn": artifact.id},
        schema=EVAL_RECORD_SCHEMA,
    )
    return artifact.id


async def upload_eval_record(
    jwt_token: Optional[str],
    job_id: str,
    record: dict,
    *,
    ivcap: Optional[Any] = None,
) -> None:
    """
    Publish the eval record. Fire-and-forget: catches and logs all exceptions so it
    can never fail or delay the crew response.

    Flow (run in a worker thread - the SDK calls are synchronous):
        1. upload the record as a JSON artifact
        2. attach an aspect to the job URN referencing that artifact

    Args:
        jwt_token: Job JWT used to build an authenticated IVCAP client (the artifact
            + aspect writes require authorization).
        job_id: Bare job id (jobCtxt.job_id); converted to the job URN internally.
        record: The eval record dict.
        ivcap: Optional pre-built IVCAP client (mainly for testing); when given,
            jwt_token is not used to construct a client.
    """
    try:
        if ivcap is None:
            if not jwt_token:
                logger.warning(
                    "No JWT token for eval upload - skipping (writes need auth)"
                )
                return
            ivcap = _authenticated_ivcap(jwt_token)

        artifact_id = await asyncio.to_thread(
            _publish_eval_record, ivcap, job_id, record
        )
        logger.info(
            "✓ Eval record uploaded as artifact %s and linked to job %s",
            artifact_id,
            job_id,
        )
    except Exception:
        logger.exception("Eval record upload failed (non-fatal)")
