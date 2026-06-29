import os
import logging
import requests
from typing import Type, List, Optional
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

ENTEREZ_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ENTEREZ_ESEARCH_URL = f"{ENTEREZ_URL}/esearch.fcgi"
ENTEREZ_EFETCH_URL = f"{ENTEREZ_URL}/efetch.fcgi"

PUBMED_MIN_YEAR = os.environ.get("PUBMED_MIN_YEAR", 2000)
PUBMED_MAX_YEAR = os.environ.get("PUBMED_MAX_YEAR", 2026)

logger = logging.getLogger(__name__)

DEFAULT_PMC_PARAMS = {"db": "pmc", "sort": "relevance"}


def call_rest_api(api_url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> requests.Response:
    """Invoke NCBI api"""
    params = params or {}
    headers = headers or {"accept": "application/json"}
    resp = requests.get(api_url, params=params, headers=headers)
    resp.raise_for_status()
    return resp

def call_ncbi_api(ncbi_url: str, params: Optional[dict] = None) -> requests.Response:
    """Invoke the NCBI API to get information"""
    if params is None:
        params = {}

    # Ensure DEFAULT_PMC_PARAMS are applied without overwriting existing keys
    for key, value in DEFAULT_PMC_PARAMS.items():
        if key not in params:
            params[key] = value

    return call_rest_api(ncbi_url, params=params)


def query_pmc_by_term(query: str, num_of_documents: int = 5) -> List[str]:
    """Search for relevant Pubmed Central documents by a query term and returns their IDs"""
    params = {
        "datetype": "pdat",
        "retmode": "json",
        "mindate": PUBMED_MIN_YEAR,
        "maxdate": PUBMED_MAX_YEAR,
        "term": query,
        "retmax": num_of_documents,
    }
    params.update(DEFAULT_PMC_PARAMS)  # Ensure default params are included
    try:
        ncbi_resp = call_ncbi_api(ENTEREZ_ESEARCH_URL, params=params)
        return ncbi_resp.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        logger.error(f"Error querying PubMed Central search term: {e}")
        return []

def query_pmc_by_pmid(pmcid_list: list[str]) -> str:
    """Search for Pubmed documents given the document identifiers

    Args:
        pmcid_list: list of Pubmed Central document ids to search

    Returns:
        the pubmed documents queried by pubmed ids
    """
    params = {"id": ",".join(pmcid_list), "retmode": "xml"}
    ncbi_resp = call_ncbi_api(ENTEREZ_EFETCH_URL, params=params)
    return ncbi_resp.content.decode("utf-8")


def clean_pmcids(pmcids: str) -> str:
    """Utility function to clean PMCID by removing 'PMC' prefix if present."""
    clean_ids = []
    had_prefix = {}

    for pmcid in pmcids:
        pmcid_str = str(pmcid).strip()
        is_prefixed = pmcid_str.upper().startswith("PMC")
        numeric_id = pmcid_str.upper().replace("PMC", "")

        if numeric_id.isdigit():
            clean_ids.append(numeric_id)
            had_prefix[numeric_id] = is_prefixed
    id_query = " OR ".join([f"{cid}[uid]" for cid in clean_ids])
    return id_query, len(clean_ids)

def filter_pmcids_by_type(pmcids, article_type="research"):
    """
    Filters a list of PMCIDs to return only those matching the specified article type.

    :param pmcids: List of PMCIDs (e.g., ['PMC7092803', 'PMC3603408'] or [7092803, 3603408])
    :param article_type: 'research' (original research) or 'review' (review articles)
    :return: A list of filtered PMCIDs, preserving the original 'PMC' prefix style if present.
    """
    if not pmcids:
        return []

    id_query, cnt = clean_pmcids(pmcids)
    # Determine the filter term
    if article_type == "review":
        filter_term = "review[filter]"
    elif article_type == "research":
        filter_term = '"research article"[Filter]'
    else:
        raise ValueError("article_type must be either 'research' or 'review'")

    # Combine the IDs and the filter
    full_term = f"({id_query}) AND {filter_term}"

    params = {"id": full_term, "retmode": "xml", "retmax": cnt}
    ncbi_resp = call_ncbi_api(ENTEREZ_EFETCH_URL, params=params)
    return ncbi_resp.content.decode("utf-8")

def translate_doi_to_pmcid(doi: str) -> Optional[str]:
    """Translate a DOI to a PMCID using the PMC ID Converter API.

    :param doi: The DOI string (e.g., '10.1038/s41586-020-2003-x')
    :return: The PMCID (e.g., 'PMC7092803') if found, otherwise None
    """
    conv_url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
    conv_params = {
        "ids": doi,
        "format": "json",
        "tool": "my_tool",
        "email": "my_email@example.com",
    }

    try:
        conv_response = requests.get(conv_url, params=conv_params)
        conv_response.raise_for_status()
        conv_data = conv_response.json()

        records = conv_data.get("records", [])
        if not records or "pmcid" not in records[0]:
            logger.warning("No PMC ID found for DOI: %s", doi)
            return None

        return records[0]["pmcid"]
    except Exception as e:
        logger.error("Error translating DOI %s to PMCID: %s", doi, e)
        return None


# CrewAI Tool Definitions

class PubMedCentralSearchInput(BaseModel):
    """Input parameters for PubMedSearchTool."""
    query: str = Field(..., description="The query term or phrase to search for in PubMedCentral.")
    article_type:str = Field(default="review", description="The type of articles to search for in PubMedCentral, e.g., 'research or review'.")
    num_of_documents: int = Field(default=10, description="The maximum number of documents to return.")

class PubMedCentralSearchByTerm(BaseTool):
    """Searches PubMed Central database using search terms for scientific literature."""
    name: str = "PubMedCentral Search By Term Tool"
    description: str = (
        "Searches PubMedCentral database using search terms for scientific literature. "
        "Returns titles and abstracts of matching articles."
    )
    args_schema: Type[BaseModel] = PubMedCentralSearchInput

    def _run(self, query: str, article_type: str="review", num_of_documents: int = 10) -> str:
        try:
            filter_str=""
            if article_type == 'review':
                filter_str = "review[Filter]"
            elif article_type == 'research':
                filter_str = "research article[Filter]"
            if filter_str:
                query = f"{query} AND {filter_str}"
            pmids = query_pmc_by_term(query, num_of_documents)
            if not pmids:
                return f"No results found for search query: '{query}'"
            return query_pmc_by_pmid(pmids)
        except Exception as exp:
            logger.error("Error during PubMed search by term: %s", exp)
            return f"An error occurred while searching PubMed for query: '{query}'. Please try again later."


class PubMedCentralIDListInput(BaseModel):
    """Schema for a list of PubMed Central IDs."""
    pmcids: List[str] = Field(..., description="A list of PubMedCentral IDs to fetch details for. should be in the format of PMC1234567.")
    article_type:str = Field(default="review", description="The type of articles to search for in PubMedCentral, e.g., 'research or review'.")

class PubMedCentralSearchByPMCID(BaseTool):
    name: str = "PubMedCentral Search By PMCID"
    description: str = (
        "Searches PubMed Central database using PMCID for scientific literature. "
        "Returns titles and abstracts of matching articles."
    )
    args_schema: Type[BaseModel] = PubMedCentralIDListInput

    def _run(self, pmcids: List[str], article_type: str = "review") -> str:
        try:
            if not pmcids:
                return "No PubMed Central IDs provided to search."
            return filter_pmcids_by_type(pmcids=pmcids, article_type=article_type)
        except Exception as exp:
            logger.exception("Error during PubMed search by PMIDs: %s", exp)
            return f"An error occurred while fetching PubMed details for PMIDs: {', '.join(pmcids)}. Please try again later."


class PubmedCentralDoiSearchInput(BaseModel):
    """Input schema for PubmedDoiSearchTool."""
    dois: List[str] = Field(
        ...,
        description="The Digital Object Identifier (DOI) of the scientific paper to find, e.g., '10.1038/s41586-020-2012-7'."
    )
    article_type:str = Field(default="review", description="The type of articles to search for in PubMedCentral, e.g., 'research or review'.")

class PubMedCentralSearchByDOI(BaseTool):
    name: str = "PubMedCentral Search By DOI"
    description: str = (
        "Searches PubMed Central database using DOI for scientific literature. "
        "Returns titles and abstracts of matching articles."
    )
    args_schema: Type[BaseModel] = PubmedCentralDoiSearchInput

    def _run(self, dois: List[str], article_type: str = "review") -> str:
        try:
            # Step 1: resolve each DOI to its PMCID via the PMC ID Converter
            pmcids = []
            for doi in dois:
                pmcid = translate_doi_to_pmcid(doi)
                if pmcid:
                    pmcids.append(pmcid)

            if not pmcids:
                return f"No PubMed Central articles found for DOIs: {', '.join(dois)}"

            # Step 2: extract the articles using the resolved PMCIDs
            return filter_pmcids_by_type(pmcids=pmcids, article_type=article_type)
        except Exception as exp:
            logger.exception("Error during PubMed Central search by DOIs: %s", exp)
            return f"An error occurred while fetching PubMed Central details for DOIs: {', '.join(dois)}. Please try again later."
