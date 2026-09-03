"""
Tests for timeout error handling in crew_runner.

Two layers are tested:
1. service_types.py — AgentA.as_crew_agent() applies AGENT_MAX_EXECUTION_TIME
   to each CrewAI Agent so that execution is bounded.
2. service.py — crew_runner wraps crew.kickoff() in a try/except that converts
   ANY exception (including TimeoutError raised when an agent exceeds its time
   budget) into HTTPException(503).
"""

import asyncio
import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Must set env vars before importing any crewai / ivcap modules.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("IVCAP_BASE_URL", "http://localhost:8077")
os.environ.setdefault("AGENT_MAX_EXECUTION_TIME", "300")

# Ensure project root is on sys.path so imports resolve correctly.
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_job_context():
    ctx = MagicMock()
    ctx.job_id = "test-job-timeout-001"
    ctx.job_authorization = None
    ctx.auth_token = None
    ctx.headers = {}
    ctx.request = MagicMock()
    ctx.request.headers = {}
    ctx.ivcap = MagicMock()
    return ctx


@pytest.fixture
def minimal_crew_request():
    """Minimal CrewRequest with one agent and one task — no artifacts."""
    from service import CrewRequest
    from service_types import AgentA, CrewA, TaskA

    return CrewRequest(
        name="timeout-test",
        inputs={},
        crew=CrewA(
            name="timeout-test-crew",
            agents=[
                AgentA(
                    name="slow_agent",
                    role="Slow Researcher",
                    goal="Research something thoroughly",
                    backstory="I work carefully but slowly",
                )
            ],
            tasks=[
                TaskA(
                    description="Take too long to complete",
                    expected_output="Results that will never arrive in time",
                    agent="slow_agent",
                )
            ],
        ),
    )


def _make_mock_crew(kickoff_side_effect):
    mock_crew = MagicMock()
    mock_crew.kickoff.side_effect = kickoff_side_effect
    mock_crew.agents = []
    mock_crew.tasks = []
    mock_crew.reset_memories = MagicMock()
    return mock_crew


def _make_mock_crew_def(mock_crew):
    mock_def = MagicMock()
    mock_def.name = "timeout-test-crew"
    mock_def.agents = []
    mock_def.tasks = []
    mock_def.as_crew.return_value = mock_crew
    return mock_def


def _run_crew_runner_expecting_http_exception(
    req, job_ctx, kickoff_exc, tmp_path, monkeypatch
):
    """
    Patch all heavy dependencies so only the kickoff() exception path executes.
    Returns the HTTPException raised by crew_runner.

    crew_runner derives its job directory from os.getcwd(), so chdir into tmp_path
    to keep the run (and the rmtree in its finally block) out of the project tree.
    patch.dict restores os.environ afterwards, discarding the CREWAI_STORAGE_DIR
    that crew_runner sets.
    """
    from fastapi.exceptions import HTTPException
    from service import crew_runner

    mock_llm = MagicMock()
    mock_llm.call.return_value = "OK"
    mock_crew = _make_mock_crew(kickoff_exc)
    mock_def = _make_mock_crew_def(mock_crew)

    monkeypatch.chdir(tmp_path)

    with (
        patch("service.get_auth_token", return_value=None),
        patch("service.load_crew_definition", return_value=mock_def),
        patch(
            "service.create_authenticated_llm",
            return_value=(mock_llm, mock_llm, None, None),
        ),
        patch("service.DownloadManager") as MockDM,
        patch.dict(os.environ, {}),
    ):
        MockDM.return_value.download.return_value = None
        MockDM.return_value.cleanup.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(crew_runner(req, job_ctx))

    return exc_info.value


# ---------------------------------------------------------------------------
# Tests: crew_runner converts kickoff() timeout into HTTPException(503)
# ---------------------------------------------------------------------------


def test_timeout_error_from_kickoff_raises_http_503(
    mock_job_context, minimal_crew_request, tmp_path, monkeypatch
):
    """
    TimeoutError raised by crew.kickoff() → HTTPException(503).

    Simulates a CrewAI agent exceeding its max_execution_time and the framework
    surfacing that as a TimeoutError back to the caller.
    """
    exc = _run_crew_runner_expecting_http_exception(
        minimal_crew_request,
        mock_job_context,
        TimeoutError("Agent exceeded max_execution_time of 300s"),
        tmp_path,
        monkeypatch,
    )

    assert exc.status_code == 503
    assert "Error in Crewai execution" in exc.detail


def test_asyncio_timeout_from_kickoff_raises_http_503(
    mock_job_context, minimal_crew_request, tmp_path, monkeypatch
):
    """
    asyncio.TimeoutError raised by crew.kickoff() → HTTPException(503).

    Covers cases where an async wall-clock deadline (e.g. asyncio.wait_for)
    wraps the crew and expires before kickoff completes.
    """
    exc = _run_crew_runner_expecting_http_exception(
        minimal_crew_request,
        mock_job_context,
        asyncio.TimeoutError("Crew wall-clock limit exceeded"),
        tmp_path,
        monkeypatch,
    )

    assert exc.status_code == 503
    assert "Error in Crewai execution" in exc.detail


def test_generic_exception_from_kickoff_raises_http_503(
    mock_job_context, minimal_crew_request, tmp_path, monkeypatch
):
    """
    Any exception from crew.kickoff() → HTTPException(503).

    Verifies the safety net is general: unexpected CrewAI failures do not leak
    internal tracebacks to the caller.
    """
    exc = _run_crew_runner_expecting_http_exception(
        minimal_crew_request,
        mock_job_context,
        RuntimeError("Unexpected failure inside crew"),
        tmp_path,
        monkeypatch,
    )

    assert exc.status_code == 503


# ---------------------------------------------------------------------------
# Tests: AGENT_MAX_EXECUTION_TIME is wired into CrewAI agents
# ---------------------------------------------------------------------------


def test_default_agent_timeout_is_300_seconds():
    """AGENT_MAX_EXECUTION_TIME defaults to 300 s (5 min) when env var is absent."""
    import service_types

    assert service_types.AGENT_MAX_EXECUTION_TIME == 300


def test_env_var_overrides_agent_timeout(monkeypatch):
    """
    AGENT_MAX_EXECUTION_TIME env var controls the timeout budget per agent.
    Reload service_types after changing the env var to verify the module picks
    up the new value.
    """
    import service_types

    monkeypatch.setenv("AGENT_MAX_EXECUTION_TIME", "60")
    importlib.reload(service_types)

    try:
        assert service_types.AGENT_MAX_EXECUTION_TIME == 60
    finally:
        monkeypatch.setenv("AGENT_MAX_EXECUTION_TIME", "300")
        importlib.reload(service_types)


def test_as_crew_agent_passes_max_execution_time_to_crewai():
    """
    AgentA.as_crew_agent() must forward AGENT_MAX_EXECUTION_TIME to CrewAI's
    Agent constructor via the max_execution_time keyword argument.
    This is the mechanism that enforces the per-agent timeout budget.
    """
    from crewai import Agent
    from service_types import AGENT_MAX_EXECUTION_TIME, AgentA, Context

    agent_spec = AgentA(
        name="test_agent",
        role="Tester",
        goal="Test things",
        backstory="I test things",
    )

    mock_job_ctx = MagicMock()
    mock_job_ctx.job_id = "unit-test-job"
    mock_job_ctx.job_authorization = None

    ctx = Context(vectordb_config={}, job_context=mock_job_ctx)

    with patch("service_types.Agent") as MockAgent:
        MockAgent.return_value = MagicMock(spec=Agent)
        agent_spec.as_crew_agent(ctx)

        _, kwargs = MockAgent.call_args
        assert kwargs.get("max_execution_time") == AGENT_MAX_EXECUTION_TIME, (
            f"Expected Agent(max_execution_time={AGENT_MAX_EXECUTION_TIME}), "
            f"got {kwargs.get('max_execution_time')}"
        )


# ---------------------------------------------------------------------------
# Tests: cleanup deletes this job's directory and nothing above it
# ---------------------------------------------------------------------------


@pytest.fixture
def crew_ref_request():
    """
    Request that names its crew by reference rather than inline.

    load_crew_definition is mocked in these tests, so the URN is never resolved.
    Using crew-ref avoids constructing a CrewA: service.py binds CrewA at import
    time, and test_env_var_overrides_agent_timeout reloads service_types, so a
    freshly-imported CrewA no longer satisfies CrewRequest's isinstance check.
    """
    from service import CrewRequest

    return CrewRequest(
        name="cleanup-test",
        inputs={},
        crew_ref="urn:ivcap:aspect:test-crew",
    )


def _seed_concurrent_job(tmp_path):
    """Create runs/some-other-job/keep.md, standing in for a concurrent job."""
    other_job = tmp_path / "runs" / "some-other-job"
    other_job.mkdir(parents=True)
    (other_job / "keep.md").write_text("concurrent job output")
    return other_job


def test_cleanup_removes_only_this_jobs_directory(
    mock_job_context, crew_ref_request, tmp_path, monkeypatch
):
    """
    The finally block removes the job's own directory while leaving runs/ and any
    concurrent job's directory untouched.
    """
    other_job = _seed_concurrent_job(tmp_path)

    _run_crew_runner_expecting_http_exception(
        crew_ref_request,
        mock_job_context,
        RuntimeError("boom"),
        tmp_path,
        monkeypatch,
    )

    assert not (tmp_path / "runs" / "test-job-timeout-001").exists()
    assert (tmp_path / "runs").exists()
    assert (other_job / "keep.md").read_text() == "concurrent job output"


def test_cleanup_refuses_to_delete_the_runs_root(
    mock_job_context, crew_ref_request, tmp_path, monkeypatch
):
    """
    A job_id that collapses the job directory onto the runs/ root must NOT trigger
    an rmtree of runs/ - that would destroy every concurrent job on the host.
    """
    mock_job_context.job_id = ""
    other_job = _seed_concurrent_job(tmp_path)

    _run_crew_runner_expecting_http_exception(
        crew_ref_request,
        mock_job_context,
        RuntimeError("boom"),
        tmp_path,
        monkeypatch,
    )

    assert (tmp_path / "runs").exists(), "runs/ root was deleted"
    assert (other_job / "keep.md").read_text() == "concurrent job output"


def test_cleanup_refuses_to_escape_the_runs_root(
    mock_job_context, crew_ref_request, tmp_path, monkeypatch
):
    """
    A traversing job_id must not let cleanup delete anything outside runs/.
    """
    mock_job_context.job_id = "../sibling"
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    (sibling / "keep.md").write_text("not ours to delete")
    (tmp_path / "runs").mkdir()

    _run_crew_runner_expecting_http_exception(
        crew_ref_request,
        mock_job_context,
        RuntimeError("boom"),
        tmp_path,
        monkeypatch,
    )

    assert (sibling / "keep.md").read_text() == "not ours to delete"
