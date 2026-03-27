"""Task definitions for the IVCAP CrewAI service."""

import os

from crewai import Agent, Task

from tools.url_metadata_extractor import URLMetadataExtractor


def create_validate_urls_task(
    agent: Agent,
    jwt_token: str,
    job_folder: str,
    output_file: str = "validated_references.md",
    markdown: bool = True,
) -> Task:
    """
    Create a task that validates URLs found in the job folder reference files.

    Uses the URL Metadata Extractor tool to fetch and verify each URL,
    returning a structured markdown report of validated references.

    Args:
        agent: The agent responsible for executing this task.
        jwt_token: JWT token for LiteLLM proxy authentication.
        job_folder: Folder where job input/output files are stored.
        output_file: Path where the task output will be saved.
        markdown: Whether the agent should return the final answer in Markdown format.

    Returns:
        A configured CrewAI Task instance.
    """
    url_metadata_extractor = URLMetadataExtractor(
        jwt_token=jwt_token,
        litellm_proxy_url=os.getenv("LITELLM_PROXY"),
        job_folder=job_folder,
        metadata_file=os.path.join(job_folder, "url_metadata.json"),
    )

    return Task(
        name="validate_urls",
        description=(
            "Validate the URLs found in the reference file located in the job folder. "
            "Use the URL Metadata Extractor tool to fetch and verify each URL, extracting "
            "metadata including title, authors, and organisation. Only include references "
            "where the URL was successfully validated (confidence scale of 5)."
        ),
        expected_output=(
            "A structured markdown report listing all validated references. For each "
            "validated URL include: title, authors, organisation, and the URL itself. "
            "Group results under a '## Validated References' heading. If no URLs could "
            "be validated, state that clearly."
        ),
        agent=agent,
        tools=[url_metadata_extractor],
        output_file=output_file,
        markdown=markdown,
    )
