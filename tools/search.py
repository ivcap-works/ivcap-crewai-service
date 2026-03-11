"""Custom search tools"""

import json
import os
from typing import Optional, Set, Dict
from pydantic import Field

from crewai_tools import WebsiteSearchTool, SerperDevTool

from ivcap_service import getLogger
from tools.url_metadata_extractor import URLMetadataFetcher

logger = getLogger(__name__)


class WebsiteSearchToolWithLinks(WebsiteSearchTool):
    """
    Website search tool that saves all searched links to a file.

    This enables other tools/agents to access the list of researched sources.
    Links are saved to a JSON file after each search operation.
    If the file exists, new links are appended to existing ones.
    """

    links: Set[str] = Field(
        description="Set of all the website links searched", default_factory=set
    )
    links_file: Optional[str] = Field(
        default=None, description="Path to JSON file where links will be saved"
    )

    def __init__(
        self,
        website: str | None = None,
        config: dict | None = None,
        links_file: str | None = None,
        collection_name: str | None = None,
        **kwargs,
    ):
        """
        Initialize WebsiteSearchToolWithLinks with ChromaDB config.

        Args:
            website: Optional website URL to search
            config: VectorDB configuration (includes ChromaDB persist_dir)
            links_file: Path to save searched links
            collection_name: ChromaDB collection name for this instance
            **kwargs: Additional parameters passed to parent class
        """
        # Pass config and collection_name to parent via kwargs
        if config is not None:
            kwargs["config"] = config
        if collection_name is not None:
            kwargs["collection_name"] = collection_name

        # Initialize parent class with all parameters
        super().__init__(website=website, **kwargs)

        # Set custom fields
        if links_file is not None:
            self.links_file = links_file

    def _run(  # type: ignore[override]
        self,
        search_query: str,
        website: str | None = None,
        similarity_threshold: float | None = None,
        limit: int | None = None,
    ) -> str:
        # Add website URL to links set (duplicates automatically handled)
        # Call parent to perform the actual search
        result = None
        try:
            result = super()._run(
                search_query=search_query,
                website=website,
                similarity_threshold=similarity_threshold,
                limit=limit,
            )
        except Exception:
            logger.exception("Error when invoking website search")
            raise
        else:
            if website:
                self.links.add(website)
            if self.links_file:
                self._save_links()

        return result

    def _save_links(self):
        """Save links to JSON file, appending to existing links if file exists"""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.links_file), exist_ok=True)

            # If file exists, load existing links and merge with current set
            if os.path.exists(self.links_file):
                try:
                    with open(self.links_file, "r") as f:
                        existing_data = json.load(f)
                        existing_links = set(existing_data.get("source_links", []))
                        # Merge existing links with current links
                        self.links = self.links.union(existing_links)
                except (json.JSONDecodeError, KeyError) as e:
                    # If file is corrupted or invalid, proceed with current links
                    logger.exception(
                        "Could not read existing links from %s: %s", self.links_file, e
                    )

            # Write merged links to file
            with open(self.links_file, "w") as f:
                json.dump({"source_links": sorted(list(self.links))}, f, indent=2)
                logger.info("Saving %s links to %s", self.links, self.links_file)
        except Exception as e:
            # Log error but don't fail the search
            logger.exception("Failed to save links to %s: %s", self.links_file, e)


class SerperDevToolWithLinks(SerperDevTool):
    """
    Serper search tool that extracts and saves all result links to a file.

    This enables other tools/agents to access the list of discovered sources.
    Links are extracted from search results, validated via URLMetadataFetcher,
    and saved to a JSON file.  If the file exists, new links are appended to
    existing ones.
    """

    links: Dict[str, str] = Field(
        description="Dictionary of links (url: title) found in search results",
        default_factory=dict,
    )
    links_file: str = Field(
        default="Path to JSON file containing researcher's source links (e.g., '{runs_base_dir}/runs/{job_id}/researcher_links.json')",
        description="Path to JSON file where links will be saved",
    )
    fetcher: URLMetadataFetcher = Field(
        default_factory=URLMetadataFetcher,
        description="Validates URLs and extracts metadata via Gemini",
    )
    jwt_token: str = Field(description="IVCAP Token", default="")

    def _run(self, search_query: str, **kwargs) -> str:  # type: ignore[override]
        # Call parent to perform the actual search
        result = super()._run(search_query=search_query, **kwargs)

        if not result:
            logger.info("No search results for query %s", search_query)
            return result

        extracted_links = self._extract_urls(result)
        if not extracted_links:
            return result

        logger.info("Validating %d extracted URLs...", len(extracted_links))
        url_entries = [
            {"url": url, "title": title} for url, title in extracted_links.items()
        ]
        validated_metadata = self.fetcher.validate_urls(
            url_entries, jwt_token=self.jwt_token, research_topic=search_query
        )
        logger.info(
            "%d/%d URLs passed validation",
            len(validated_metadata),
            len(extracted_links),
        )
        logger.info("Validated links %s", validated_metadata)

        # Persist validated links (url -> title, falling back to original title)
        if validated_metadata:
            result["validated_references"] = validated_metadata
            for url, meta in validated_metadata.items():
                self.links[url] = meta.get("title") or extracted_links[url]
            self._save_links()

        # Filter the result to only include validated URLs
        invalid_urls = set(extracted_links) - set(validated_metadata)
        if invalid_urls:
            logger.info("Invalid links %s", invalid_urls)
            result = self._filter_result(result, invalid_urls)

        return result

    def _filter_result(self, result, invalid_urls: set):
        """Remove entries with invalid URLs from the search result."""
        # Normalise: result may be a pre-parsed dict or a JSON string
        parsed, was_string = None, False
        if isinstance(result, dict):
            parsed = result
        else:
            try:
                parsed = json.loads(result)
                was_string = True
            except (json.JSONDecodeError, TypeError):
                return result  # Can't parse; return as-is

        def _drop_invalid(items: list, url_key: str) -> list:
            return [item for item in items if item.get(url_key) not in invalid_urls]

        if "organic" in parsed and isinstance(parsed["organic"], list):
            parsed["organic"] = _drop_invalid(parsed["organic"], "link")

        if "answerBox" in parsed and isinstance(parsed["answerBox"], dict):
            if parsed["answerBox"].get("link") in invalid_urls:
                del parsed["answerBox"]

        if "knowledgeGraph" in parsed and isinstance(parsed["knowledgeGraph"], dict):
            if parsed["knowledgeGraph"].get("website") in invalid_urls:
                del parsed["knowledgeGraph"]

        return json.dumps(parsed) if was_string else parsed

    def _extract_urls(self, result_text: str) -> Dict[str, str]:
        """Extract all URLs and titles from the JSON formatted search results"""
        to_links = {}

        try:
            # Parse the JSON result
            data = result_text

            # Extract links and titles from organic search results
            if "organic" in data and isinstance(data["organic"], list):
                for item in data["organic"]:
                    if "link" in item:
                        url = item["link"]
                        title = item.get("title", "No title found")
                        to_links[url] = title

            # Extract link and title from answer box if present
            if "answerBox" in data and isinstance(data["answerBox"], dict):
                if "link" in data["answerBox"]:
                    url = data["answerBox"]["link"]
                    title = data["answerBox"].get("title", "No title found")
                    to_links[url] = title

            # Extract link and title from knowledge graph if present
            if "knowledgeGraph" in data and isinstance(data["knowledgeGraph"], dict):
                if "website" in data["knowledgeGraph"]:
                    url = data["knowledgeGraph"]["website"]
                    title = data["knowledgeGraph"].get("title", "No title found")
                    to_links[url] = title

        except json.JSONDecodeError as e:
            logger.exception("Failed to parse search results as JSON: %s", e)
        except Exception as e:
            logger.exception("Failed to extract URLs from search results: %s", e)

        return to_links

    def _save_links(self):
        """Save links to JSON file, appending to existing links if file exists"""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.links_file), exist_ok=True)

            # If file exists, load existing links and merge with current dictionary
            if os.path.exists(self.links_file):
                try:
                    with open(self.links_file, "r") as f:
                        existing_data = json.load(f)
                        existing_links = existing_data.get("source_links", {})
                        saved_links = {
                            link_dict.get("url"): link_dict.get("title")
                            for link_dict in existing_links
                        }
                        # Merge existing links with current links (current links take precedence)
                        merged_links = {**saved_links, **self.links}
                        self.links = merged_links
                except (json.JSONDecodeError, KeyError) as e:
                    # If file is corrupted or invalid, proceed with current links
                    logger.exception(
                        "Could not read existing links from %s: %s", self.links_file, e
                    )

            # Write merged links to file
            with open(self.links_file, "w") as f:
                link_dict = [
                    {"url": link, "title": title} for link, title in self.links.items()
                ]
                json.dump({"source_links": link_dict}, f, indent=2)
                logger.info(
                    "Links saved to %s. Number of saved links %s",
                    self.links_file,
                    len(self.links),
                )
        except Exception as e:
            # Log error but don't fail the search
            logger.exception("Failed to save links to %s: %s", self.links_file, e)
