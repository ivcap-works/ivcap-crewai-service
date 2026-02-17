"""
URL Metadata Extractor Tool
Uses Claude's web_fetch tool to fetch URLs and extract metadata.
"""

import json
import os
from typing import Type, Optional, List, Dict
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from anthropic import Anthropic

from ivcap_service import getLogger

logger = getLogger(__name__)

# import httpx
# from anthropic import Anthropic, DefaultHttpxClient

# client = Anthropic(
#     http_client=DefaultHttpxClient(
#         proxy="http://my.test.proxy.example.com",
#         transport=httpx.HTTPTransport(local_address="0.0.0.0"),
#     ),
# )

class URLMetadataInput(BaseModel):
    """Input schema for URL metadata extraction"""
    url: str = Field(
        description="The URL to fetch and extract metadata from"
    )
    research_topic: str = Field(description="The user's research topic.")
    title: Optional[str] = Field(
        default=None,
        description="Optional pre-populated title for the URL"
    )


class URLInfo(BaseModel):
    """Structured information extracted from a URL"""
    title: Optional[str] = Field(description="The title of the webpage, article, or paper", default="")
    authors: Optional[List[str]] = Field(description="Comma-separated list of authors, or 'Not found' if unavailable", default_factory=list)
    organisation: Optional[str] = Field(description="The publishing organization, institution, or website", default="")
    inferred: bool = Field(default=False, description="The URL information is not inferred from web search")


METADATA_EXTRACTION = """You have access to web_fetch and web_search tool. Use it to fetch this URL and extract metadata:

URL: {url}

Extract the following information from the webpage:
1. **Title**: The main title of the article, paper, or webpage
2. **Authors**: Full names of all authors (comma-separated list)
3. **Organization**: The publishing organization, institution, journal, or website

Return the information in JSON format with the following keys:

Title: [extracted title]
Authors: [author1, author2, author3] or "Not found"
Organization: [organization name] or "Not found"

Be thorough - check meta tags, headers, bylines, and structured data."""

METADATA_EXTRACTION_v2 = """You have access to web_fetch and web_search tool. Use it to fetch this URL and extract metadata.
If the URL is not directly accessible or if the URL from the search result is different from the provided URL, return "Not Found" instead. 

URL: {url}
Extract the page information after page is resolved . If you are unable to directly access the page, return  "Not found" for all keys 

Extract the following information from the webpage:
1. **Title**: The main title of the article, paper, or webpage or "Not Found" if page is not directly accessible
2. **Authors**: Full names of all authors (comma-separated list) or "Not Found" if page is not directly accessible
3. **Organization**: The publishing organization, institution, journal, or website or "Not Found" if page is not directly accessible
4. Inferred: true/ false - (true if the metadata is inferred from related pages on the same website rather than extracted directly from the target URL., false otherwise)

Return the information in JSON format with the following keys:

title: [extracted title]
authors: [author1, author2, author3] or "Not found"
organization: [organization name] or "Not found"
inferred: [true/false]

Be thorough - check meta tags, headers, bylines, and structured data. Validate the correctness of your response before responding."""

METADATA_EXTRACTION_v3="""You are provided with a research topic and a URL related to the topic. You have access to web fetch and web_search tool. You need to use them to look up metadata information about this URL.
Verify that the data is related to the research topic. 
Here is a step by step approach for metadata extraction. 
1. Perform a Web Fetch using the given URL. 
2. If you get results using Web Fetch, extract metadata directly. Respond with the provided metadata. Otherwise proceed to next step. 
3. Perform a Web Search using the given URL.
4. If the search results are returned, continue to next step. Otherwise proceed to step 7.
4. If the search results are returned, consider only the first result. 
5. If the first result looks correct, extract the required metadata.
6. Discard all the other web results.
7. Return with "Not Found". Do not query your internal knowledge base.
8. Verify the result. Validate that the resulting webpage is relevant to the research topic. If the result looks correct, then extract metadata. 
If the URL has a DOI and the DOI is not found or does not exist, return immediately. Do not look outside the given results.

Search URL: {{url}}

Associated Research topic- {{research_topic}}
Extract the page information . Validate that the extracted data is related to the research topic.


Extract the following information from the webpage:
1. **Title**: The main title of the article, paper, or webpage or "Not Found" 
2. **Authors**: Full names of all authors (comma-separated list) or "Not Found" 
3. **Organization**: The publishing organization, institution, journal, or website or "Not Found" 
4. **URL**: The url of the webpage from which information is extracted
4. Inferred: true/ false - (true if the metadata is inferred from related pages on the same website rather than extracted directly from the target URL., false otherwise)

Return the information in JSON format with the following keys:

title: [extracted title]
authors: [author1, author2, author3] or "Not found"
organization: [organization name] or "Not found"
inferred: [true/false]

Be thorough - check meta tags, headers, bylines, and structured data. Validate the correctness of your response before responding."""

tools = [
    # {
    #     "name": "get_url_metadata",
    #     "description": "Returns url metadata from the message",
    #     "input_schema": {
    #         "type": "object",
    #         "properties": {
    #             "Title": {"type": "string"},
    #             "Authors": {"type": "array", "items": { "type": "string" }},
    #             "Organisation": {"type": "string"}
    #         },
    #     }
    # },
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
    model: str = Field(default="claude-sonnet-4-5-20250929", description="Claude model to use")
    metadata_file: Optional[str] = Field(default=None, description="Path to JSON file where metadata will be saved")
    metadata_cache: Dict[str, Dict] = Field(default_factory=dict, description="Cache of extracted metadata")
    url_count: int = Field(description="Total number of resolved references", default=0)

    def _run(self, url: str, research_topic: str, title: str = None) -> str:
        """
        Fetch URL and extract metadata using Claude with web_fetch tool.

        Args:
            url: The URL to fetch and parse
            research_topic: The user's research topic
            title: the title of the web page as found by the search tool

        Returns:
            Formatted string with extracted metadata
        """
        if not self.litellm_proxy_url:
            return "Error: LiteLLM proxy URL not configured. Set LITELLM_PROXY_URL environment variable."
        self.url_count += 1
        result_dict = {
            "URL": url,
            "Title": "",
            "Authors": "",
            "Organization": "",
            "Valid": False
        }
        if title:
            result_dict["Title"] = title
        # Create Anthropic client pointed at LiteLLM proxy
        client = Anthropic(
            # base_url=f"{proxy_url}",  # LiteLLM exposes Anthropic-compatible endpoint
            # default_headers=default_headers,
            api_key=os.getenv("ANTHROPIC_API_KEY")  # JWT passed as API key through proxy
        )
        is_valid = False
        try:
            # Get proxy URL (default to environment variable)
            # Construct prompt for metadata extraction
            # output_format={"type": "json_schema", "schema": URLInfo.model_json_schema()},
            # Call Claude with web_fetch tool enabled
            response = client.messages.parse(
                model=self.model,
                max_tokens=2000,
                tools=tools,
                messages=[
                    {"role": "user", "content": METADATA_EXTRACTION_v3.format(url=url, research_topic=research_topic)}
                ],
                extra_headers={
        "anthropic-beta": "web-fetch-2025-09-10"},
        output_format=URLInfo
        )
            
            # Extract and save metadata
            url_info = response.parsed_output
            if url_info and self.metadata_file:
                if not url_info.inferred:
                    if url_info.title and url_info.title.lower()!='not found':
                        result_dict["Title"] = url_info.title
                        is_valid = True
                    if url_info.authors and url_info.authors.lower() != 'not found':
                        result_dict["Authors"] = str(url_info.authors)
                        is_valid = True
                    if url_info.organisation and url_info.organisation.lower() !='not found':
                        result_dict["Organization"] = url_info.organisation
                        is_valid = True
                    
                # for content in result_text:
                #     if content.type=='tool_use' and content.name=='get_url_metadata':
                #         response_dict = content.input   
                #         if "Title" in response_dict and not response_dict["Title"] == 'Not Found':
                #             result_dict["Title"] = response_dict["Title"]
                #         if "Organisation" in response_dict and not response_dict["Organisation"] == 'Not Found':
                #             result_dict["Organisation"] = response_dict["Organisation"]
                #         if "Authors" in response_dict and not response_dict["Authors"] == 'Not Found':
                #             result_dict["Authors"] = response_dict["Authors"]
            

        except Exception as e:
            logger.exception("Error extracting metadata for url %s", url)
            return f"Error extracting metadata from {url}: {str(e)}"
        if is_valid:
            result_dict["Valid"] = True
            self.metadata_cache[str(self.url_count)] = result_dict
            self._save_metadata()
        else:
            logger.info("%s URL could not be validated.", url)
        return result_dict

    def _save_metadata(self):
        """Save metadata to JSON file, appending to existing metadata if file exists"""
        if not self.metadata_file:
            return

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
