"""
URL Metadata Extractor Tool
Uses Claude's web_fetch tool to fetch URLs and extract metadata.
"""

import json
import os
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Type, Optional, Dict
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from google.genai import Client, types
from openai import OpenAI

from ivcap_service import getLogger

logger = getLogger(__name__)

class URLMetadataInput(BaseModel):
    """Input schema for URL metadata extraction"""
    file_path: str = Field(
        description="Path to a JSON file containing a list of objects, each with a 'url' field and optionally a 'title' field"
    )
    research_topic: str = Field(description="The user's research topic.")

class URLInfo(BaseModel):
    title: str = Field(description="The title of the webpage, article, or paper", default="")
    authors: list[str] = Field(description="Comma-separated list of authors, or 'Not found' if unavailable", default_factory=list)
    organisation: str = Field(description="The publishing organization, institution, or website", default="")
    url: str = Field(description="The url from web search or web fetch tool", default="")
    confidence_scale: int = Field(description="The scale for how confident the model is about the result", default=1)

METADATA_EXTRACTION="""You are a research assistant tasked with verifying the existence of a given URL. Additionally you will be extracting metadata from the given URL (web source). Your results must be accurate and reliable.  You will be given a URL and a research topic (mandatory) and optional list of ground truths that must be associated with the web page. The optional list of ground truths are [title, DOI, PMC id].
You need to retrieve and validate metadata information using available web tools. Do NOT use your internal knowledge base to arrive at the response. 

Here is the URL you need to investigate:

<url>
{url}
</url>

Here is the associated research topic:

<research_topic>
{research_topic}
</research_topic>

Optional Title of the page. If present, perform the Title validation otherwise skip the title validation
<title>
{title}
</title>

If DOI is in the URL path, then use DOI when analysing the page. If present, perform the DOI validation, otherwise skip the DOI validation.
<doi>
{doi}
<doi>

If PMC is present in the URL path, then use the PMC ID when analysing the page. If present, perform the PMC validation, otherwise skip the PMC validation. 
<pmc>
{pmc}
</pmc>

## Your Task

Verify the given URL and extract metadata from the web page. You have access to `web_fetch` and `web_search` tools that you must use to retrieve information.

## Step-by-Step Process

Follow these steps in order:

**Step 1:** Perform a Web Fetch using the given URL.

**Step 2:** If Web Fetch returns results:
- Proceed to Step 7
- Otherwise proceed to Step 3

**Step 3:** If Web Fetch does not return results, perform a Web Search using the given URL.

**Step 4:** If Web Search does not return any results, proceed to Step 9. Otherwise proceed to Step 5.

**Step 5:** If Web Search returns results, consider ONLY the first result. Discard all other results.

**Step 6:** Check if the URL contains a DOI:
- If the URL contains a DOI and the DOI does not exist in the search results, return "Not Found" immediately and proceed to Step 9.
- Do not search beyond the provided results

**Step 7: ** Before finalizing your response, perform Validation to ensure correctness and accuracy.
- Validate that the webpage content is broadly relevant to the research topic
- if title is present, validate that the title of your page starts with the given title
- if the URL has a DOI, validate that the DOI is present and is the same as in your web page
- If the URL has a PMC, validate the PMC is present and is exactly the same in your web page
- If the result looks correct and relevant, extract the metadata

** Step 8:** Extract Metadata
Ensure the metadata is extract from a single webpage
 
**Step 9:** If no valid results were found through either method, return "Not Found" as the response. 

**Step 10:** Before finalizing your response:
- If the result looks correct and relevant, extract the metadata
- If not relevant, return "Not Found"

## Metadata to Extract

Extract the following information:

1. **Title**: The main title of the article, paper, or webpage. Use "Not Found" if unavailable.
2. **Authors**: Full names of all authors as a list. Use "Not Found" if unavailable.
3. **Organization**: The publishing organization, institution, journal, or website name. Use "Not Found" if unavailable.
4. **URL**: The URL of the web search or web fetch result page from which information was extracted.
5. **confidence-scale**: How confident you are of the results in a scale of 1-5. 1 being lowest and 5 being highest


## Important Guidelines

- Be thorough in your extraction: check meta tags, headers, bylines, and structured data
- Only use information from the web tools; do not rely on your internal knowledge
- Validate that page content is broadly relevant to the research topic
- Optional validations such as title, doi, pmc can be associated with the web page.
- When using web search, only consider the first result returned

## Output Format

Before providing your final answer, document your step-by-step process inside <analysis> tags. It's OK for this section to be quite long. Include:

- **Tool Usage**: Which tool(s) you used (web_fetch or web_search) and what happened
- **Content Quotes**: Quote relevant snippets from the fetched or searched content that contain the metadata you're extracting
- **Field-by-Field Extraction**: For each metadata field (title, authors, organization), explicitly note what you found or why it's "Not Found"
- **Relevance Validation**: Explain how the content relates to the research topic, quoting specific passages that demonstrate relevance (or explain why it's not relevant)
- **Confidence-scale**: Clearly state how confident you are of the URL validity as a result of the analysis.

Then provide your final response as a JSON object with the following structure:

Return the information in JSON format with the following keys:
"title": "[extracted title or 'Not Found']",
"authors": ["author1", "author2", "author3"] OR "Not Found",
"organization": "[organization name or 'Not Found']",
"url": "[URL from which meta data was extracted]",
"confidence-scale": "integer , scale how confident you are of the results. [1-5]"
"""


tools = [
    {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 1
    },
    {
        "type": "web_fetch_20250910",
        "name": "web_fetch",
        "max_uses": 5,
        "citations": {"enabled": True}
    }
]

class URLMetadataExtractor(BaseTool):
    """
    Fetches a URL using Claude's web_fetch tool and extracts metadata.

    This tool uses Claude (via Anthropic API) with web_fetch capability to:
    1. Fetch the webpage content from the internet
    2. Parse and extract title, authors, and organization
    3. Return structured metadata in a consistent format

    The tool uses the LiteLLM proxy URL and JWT authentication for access.
    """

    name: str = "URL Metadata Extractor"
    description: str = (
        "Fetches a URL using Claude's web capabilities and extracts metadata including "
        "title, authors, and organization. Returns formatted metadata: "
        "Title, Authors, Organization, URL. Use this to validate reference information."
    )
    args_schema: Type[BaseModel] = URLMetadataInput

    # JWT token for authentication (injected during tool creation)
    jwt_token: Optional[str] = Field(default=None, description="JWT token for LiteLLM proxy authentication")
    litellm_proxy_url: Optional[str] = Field(default=os.getenv("LITELLM_PROXY_URL"), description="LiteLLM proxy URL")
    model: str = Field(default="gemini-2.5-pro", description="LLM model to use")
    metadata_file: Optional[str] = Field(default=None, description="Path to JSON file where metadata will be saved")
    metadata_cache: Dict[str, Dict] = Field(default_factory=dict, description="Cache of extracted metadata")
    job_folder: str = Field(description="The folder where all documents for the job are kept")


    def _run(self, file_path: str, research_topic: str) -> str:
        """
        Fetch URL and extract metadata using Gemini with web_fetch tool.

        Args:
            file_path: Path to a JSON file containing 'url' and optionally 'title'
            research_topic: The user's research topic

        Returns:
            Formatted string with extracted metadata
        """
        # if not self.litellm_proxy_url:
        #     return "Error: LiteLLM proxy URL not configured. Set LITELLM_PROXY_URL environment variable."
        file_path = f"{self.job_folder}/{file_path}"
        logger.info("Reading file %s", file_path)
        if not os.path.exists(file_path):
            logger.info("%s file not found")
            return []
        try:
            with open(file_path, 'r') as f:
                file_data = json.load(f)
        except Exception:
            logger.exception("Error reading %s", file_path)
            return []
        if "source_links" not in file_data:
            logger.exception("Links not found %s", file_data)
            return []

        url_list = file_data.get("source_links", [])
        if not url_list:
            return f"Error: Expected a list of URL objects in {file_path}"
        
        to_be_validated = [item for item in url_list if item.get("url") not in self.metadata_cache]
        client = Client(api_key=os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY")))
        to_be_validated = to_be_validated[:30]
        logger.info("Validating %s URLS %s", len(to_be_validated), to_be_validated)
        with ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(self._fetch_url_metadata, client, entry, research_topic): entry
                for entry in to_be_validated
                if entry.get("url") or entry.get("URL")
            }
        
            for future in as_completed(futures):
                try:
                    result_dict = future.result()
                    if result_dict.confidence_scale==5:
                        self.metadata_cache[result_dict.url] = result_dict.model_dump()
                except Exception:
                    logger.exception("Received exception ")
                    continue
            
        self._save_metadata()
        return self.metadata_cache

    def _fetch_url_metadata(self, client: Client, entry: Dict, research_topic: str) -> URLInfo:
        """Extract metadata for a single URL entry using the Anthropic API."""
        url = entry.get("url") or entry.get("URL")
        title = entry.get("title") or entry.get("Title")
        tool_config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch()), types.Tool(url_context=types.UrlContext())], temperature=0)
        params = {
        "url": url,
        "title": title or "",
        "doi": "",
        "pmc": "",
        "research_topic": research_topic
        }
        parsed_url = urlparse(url)

        if "doi" in parsed_url.netloc.lower():
            params["doi"] = parsed_url.path
        if "pmc" in parsed_url.netloc.lower():
            params["pmc"] = parsed_url.path
        try:
            # Uses the google genai client as the langchain client doesn't return grounding metadata
            response = client.models.generate_content(
                model=self.model,
                contents=METADATA_EXTRACTION.format(**params),
                config=tool_config)
        except Exception as exp:
            logger.exception("Exception during web research node %s", exp)
            return URLInfo()

        # logger.info(response.text)
        if response.text:
            try:
                url_info = self._parse_response_with_openai(response.text)
            except Exception:
                logger.exception("Exception. Returning empty")
                return URLInfo()
            return url_info

        return URLInfo()

    def _parse_response_with_openai(self, response_text: str) -> URLInfo:
        """Use OpenAI structured output to extract typed metadata from a raw Gemini response."""
        openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        try:
            completion = openai_client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Extract the metadata fields from the provided text into the structured format."},
                    {"role": "user", "content": response_text}
                ],
                response_format=URLInfo
            )
            return completion.choices[0].message.parsed
        except Exception as e:
            logger.exception("Error parsing response with OpenAI for structured output")
            return URLInfo()

    def _save_metadata(self):
        """Save metadata to JSON file, appending to existing metadata if file exists"""
        if not self.metadata_file:
            return
        logger.info("Saving the metadata file")
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.metadata_file), exist_ok=True)

            # If file exists, load existing metadata and merge
            if os.path.exists(self.metadata_file):
                try:
                    with open(self.metadata_file, 'r') as f:
                        existing_data = json.load(f)
                        existing_metadata = existing_data.get("url_metadata", {})
                        # Merge with current cache
                        self.metadata_cache = existing_metadata | self.metadata_cache
                except (json.JSONDecodeError, KeyError) as e:
                    logger.exception("Warning: Could not read existing metadata from %s: %s" , self.metadata_file, e)

            # Write merged metadata to file
            with open(self.metadata_file, 'w') as f:
                json.dump({
                    "url_metadata": self.metadata_cache
                }, f, indent=2)
                logger.info("No of links updated %s", len(self.metadata_cache))
        except Exception as e:
            logger.exception("Warning: Failed to save metadata to %s: %s ", self.metadata_file, e)
