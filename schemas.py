"""
Request / Response schemas for the IVCAP CrewAI Service.

Pydantic models defining the public contract of the crew_runner endpoint:
  - CrewRequest:  the incoming crew-execution request
  - CrewResponse: the result returned to the caller
"""

from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from crewai.types.usage_metrics import UsageMetrics

from service_types import CrewA, TaskResponse


class CrewRequest(BaseModel):
    """Request to execute a CrewAI crew."""

    jschema: str = Field("urn:sd-core:schema.crewai.request.1", alias="$schema")
    name: str = Field(description="Name of this crew execution")
    inputs: Optional[dict] = Field(None, description="Input variables for crew")

    # Crew definition (one of these required)
    crew_ref: Optional[str] = Field(
        None,
        description="IVCAP aspect URN referencing crew definition",
        alias="crew-ref",
    )
    crew: Optional[CrewA] = Field(None, description="Inline crew definition")

    # Optional features
    context_urns: Optional[list[str]] = Field(
        None,
        description="IVCAP Aspect URNs. Download the Artifact urn's using the Aspect URN's",
        alias="context-urns",
    )
    enable_citations: Optional[bool] = Field(
        False, description="Enable citation tracking (experimental)"
    )

    model_config = ConfigDict(populate_by_name=True)

    additional_inputs: Optional[Union[str, list[str]]] = Field(
        "",
        description="[Deprecated]Previous crew outputs as markdown (string or list of strings). Use context-urns instead",
        alias="additional-inputs",
    )


class CrewResponse(BaseModel):
    """Response from crew execution."""

    jschema: str = Field("urn:sd-core:schema.crewai.response.1", alias="$schema")
    answer: str = Field(description="Final crew output")
    crew_name: str = Field(description="Name of executed crew")
    place_holders: list = Field(description="Placeholders used")
    task_responses: Optional[list[TaskResponse]] = Field(
        description="Individual task outputs", default_factory=list
    )
    created_at: str = Field(description="Execution timestamp")
    process_time_sec: float = Field(description="CPU time")
    run_time_sec: float = Field(description="Wall clock time")
    token_usage: UsageMetrics = Field(description="LLM token usage")
    citations: Optional[dict] = Field(None, description="Citation report if enabled")
