"""
IVCAP LangGraph Research Tool

Wraps the IVCAP LangGraph research service as a CrewAI tool.
This allows CrewAI agents to leverage the powerful LangGraph-based
research agent for comprehensive web research with citations.

The LangGraph service performs iterative research with:
- Query generation
- Parallel web searches
- Reflection and knowledge gap analysis
- Citation tracking
- Synthesized answers

Usage in crew definitions:
{
  "tools": [{
    "id": "urn:ivcap:langgraph:deep-research",
    "name": "deep_research",
    "opts": {
      "initial_search_query_count": 3,
      "max_research_loops": 2
    }
  }]
}
"""

from __future__ import annotations
from typing import Any, Optional, Type
import os
import logging
from time import sleep
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
from ivcap_client import IVCAP
from ivcap_client.job import JobStatus

logger = logging.getLogger("app.langgraph_tool")


class LangGraphResearchInput(BaseModel):
    """Input schema for the LangGraph research tool"""
    query: str = Field(
        ...,
        description="The research question or topic to investigate. Be specific and clear."
    )
    initial_search_query_count: int = Field(
        default=3,
        description="Number of initial search queries to generate (1-10). More queries = broader coverage.",
        ge=1,
        le=10
    )
    max_research_loops: int = Field(
        default=2,
        description="Maximum research iterations for knowledge gap analysis (1-5). More loops = deeper research.",
        ge=1,
        le=5
    )


class IvcapLangGraphTool(BaseTool):
    """
    CrewAI tool wrapper for the IVCAP LangGraph research service.

    This tool calls an external LangGraph-based research agent that:
    1. Generates diverse search queries from the research question
    2. Performs parallel web searches using Google Search API
    3. Analyzes results to identify knowledge gaps
    4. Iteratively refines research until comprehensive
    5. Synthesizes findings with proper citations

    The tool returns a comprehensive research report with citations that
    can be used by CrewAI agents in their tasks.
    """

    name: str = "deep_research"
    description: str = (
        "Performs comprehensive web research using an advanced LangGraph agent. "
        "This tool conducts multi-round research with reflection and knowledge gap analysis. "
        "It generates diverse search queries, performs parallel web searches, "
        "identifies missing information, and synthesizes findings with citations. "
        "Use this when you need thorough, well-researched information with source attribution. "
        "Input: A clear research question. "
        "Output: Comprehensive research report with citations."
    )
    args_schema: Type[BaseModel] = LangGraphResearchInput

    service_urn: str = Field(
        default="urn:ivcap:service:dcdc770b-d276-5df5-b5b7-babf17fa6eb7",
        description="IVCAP service URN for the LangGraph research service"
    )
    jwt_token: Optional[str] = Field(
        default_factory=lambda: os.getenv("IVCAP_JWT_TOKEN")
    )

    def _run(
        self,
        query: str,
        initial_search_query_count: int = 3,
        max_research_loops: int = 2,
    ) -> str:
        """
        Execute research using IVCAP SDK (handles polling automatically).

        Args:
            query: Research question to investigate
            initial_search_query_count: Number of initial search queries (1-10)
            max_research_loops: Maximum research iterations (1-5)

        Returns:
            Comprehensive research report with citations

        Raises:
            Exception: If the service call fails or times out
        """
        try:
            logger.info(
                f"Initiating LangGraph research for query: '{query[:100]}...' "
                f"(queries={initial_search_query_count}, loops={max_research_loops})"
            )

            # Initialize IVCAP Client
            if self.jwt_token and self.jwt_token.strip():
                logger.debug(f"Using JWT token (length: {len(self.jwt_token)})")
                ivcap = IVCAP(token=self.jwt_token)
            else:
                logger.warning("No JWT token available - attempting without authentication")
                ivcap = IVCAP()

            # Get Service
            logger.info(f"Getting service: {self.service_urn}")
            service = ivcap.get_service(self.service_urn)

            # Create Request (request_model is a property, not a method!)
            logger.info("Creating request model...")
            request_model = service.request_model
            request = request_model(
                query=query,
                initial_search_query_count=initial_search_query_count,
                max_research_loops=max_research_loops
            )

            # Submit Job
            logger.info("Submitting job to LangGraph service...")
            job = service.request_job(request)
            logger.info(f"Job submitted: {job.id}")

            # Poll for job completion (sync SDK requires manual polling)
            poll_interval = 10  # seconds
            max_wait = 600  # 10 minutes max
            waited = 0

            logger.info(f"Polling for job completion (max {max_wait}s, interval {poll_interval}s)...")
            while not job.refresh().finished:
                if waited >= max_wait:
                    raise Exception(f"Job timed out after {max_wait}s: {job.id}")
                status = job.status()
                logger.info(f"Job status: {status.value}, waiting... ({waited}s elapsed)")
                sleep(poll_interval)
                waited += poll_interval

            # Check job succeeded
            final_status = job.status()
            logger.info(f"Job finished with status: {final_status.value}")
            if final_status != JobStatus.SUCCEEDED:
                raise Exception(f"Job failed with status: {final_status.value}")

            # Access result (property, not method!)
            result = job.result

            # Extract output
            if result is None:
                output = "Research completed but no result returned"
            elif isinstance(result, dict):
                output = result.get("output") or result.get("result") or str(result)
            else:
                output = str(result)

            logger.info(f"Research completed successfully ({len(output)} chars)")
            return output

        except Exception as e:
            error_msg = f"Error in LangGraph research: {str(e)}"
            logger.error(error_msg)
            logger.exception(e)
            raise Exception(error_msg) from e


def create_langgraph_tool(
    tool_spec: Any,
    context: Any,
    service_urn: Optional[str] = None,
    jwt_token: Optional[str] = None
) -> IvcapLangGraphTool:
    """
    Factory function to create LangGraph tool instances.

    This matches the signature expected by service_types.py's supported_tools registry.

    Args:
        tool_spec: Tool specification from crew definition (contains opts)
        context: Runtime context (contains jwt_token, etc.)
        service_urn: Optional override for service URN
        jwt_token: Optional override for JWT token

    Returns:
        Configured IvcapLangGraphTool instance
    """
    # Extract configuration from tool spec options
    opts = tool_spec.opts or {}

    # Create tool with configuration
    tool = IvcapLangGraphTool()

    # Override service URN if provided
    if service_urn:
        tool.service_urn = service_urn

    # Use JWT token from context if available
    if hasattr(context, 'jwt_token') and context.jwt_token and str(context.jwt_token).strip():
        tool.jwt_token = str(context.jwt_token).strip()
        logger.debug(f"Using JWT token from context (length: {len(tool.jwt_token)})")
    elif jwt_token and str(jwt_token).strip():
        tool.jwt_token = str(jwt_token).strip()
        logger.debug(f"Using provided JWT token (length: {len(tool.jwt_token)})")
    else:
        tool.jwt_token = None
        logger.warning("No valid JWT token available for LangGraph tool")

    logger.info(f"Created LangGraph tool: {tool.name} -> {tool.service_urn}")
    return tool
