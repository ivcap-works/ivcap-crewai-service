import os
import logging
import requests
import xml.etree.ElementTree as ET
from typing import Type, List, Optional
from pydantic import BaseModel, Field
from crewai.tools import BaseTool
# If get_secret_api_key is available in your local directory structure:

def set_ncbi_key():
    try:
        from ivcap_ai_tool import SecretMgrClient
        secret_mgr_client = SecretMgrClient()
        secret_key = secret_mgr_client.get_secret(secret_name="NCBI_API_KEY", is_shared_secret=True)
        os.environ["NCBI_API_KEY"] = secret_key
    except ImportError:
        # Fallback to os.environ if local import is unavailable
        NCBI_API_KEY = os.environ.get("NCBI_API_KEY")

ENTEREZ_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
ENTEREZ_ESEARCH_URL = f"{ENTEREZ_URL}/esearch.fcgi"
ENTEREZ_EFETCH_URL = f"{ENTEREZ_URL}/efetch.fcgi"

PUBMED_MIN_YEAR = os.environ.get("PUBMED_MIN_YEAR", 2000)
PUBMED_MAX_YEAR = os.environ.get("PUBMED_MAX_YEAR", 2026)

LLM_TO_USE = os.environ.get("LLM_TO_USE", "gpt-4o")
PUBMED_LLM = os.environ.get("PUBMED_LLM", LLM_TO_USE)

logger = logging.getLogger(__name__)

DEFAULT_PUBMED_PARAMS = {"db": "pubmed", "sort": "relevance"}


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
    
    # params["api_key"] = os.environ.get("NCBI_API_KEY", "")
    # Ensure DEFAULT_PUBMED_PARAMS are applied without overwriting existing keys
    for key, value in DEFAULT_PUBMED_PARAMS.items():
        if key not in params:
            params[key] = value
            
    return call_rest_api(ncbi_url, params=params)


def fetch_pubmed_details(pmids: List[str]) -> str:
    """Fetches titles and abstracts for a list of PubMed IDs using efetch.fcgi"""
    if not pmids:
        return "No articles found."

    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml"
    }

    try:
        # efetch returns XML data
        response = call_rest_api(ENTEREZ_EFETCH_URL, params=params, headers={"accept": "application/xml"})
        root = ET.fromstring(response.content)
        
        articles_summary = []
        for article in root.findall(".//PubmedArticle"):
            # Extract PMID
            pmid_el = article.find(".//PMID")
            pmid = pmid_el.text if pmid_el is not None else "N/A"
            
            # Extract Title
            title_el = article.find(".//ArticleTitle")
            title = title_el.text if title_el is not None else "No Title Available"
            
            # Extract Abstract
            abstract_texts = article.findall(".//AbstractText")
            if abstract_texts:
                abstract = " ".join([elem.text for elem in abstract_texts if elem.text])
            else:
                abstract = "No Abstract Available"
                
            articles_summary.append(
                f"PMID: {pmid}\nTitle: {title}\nAbstract: {abstract}\n"
            )
            
        return "\n---\n".join(articles_summary)

    except Exception as e:
        logger.error(f"Failed to fetch details from PubMed: {e}")
        return f"Error occurred while retrieving article details for PMIDs: {', '.join(pmids)}"


def query_pubmed_by_term(query: str, num_of_documents: int = 5) -> List[str]:
    """Search for relevant Pubmed documents by a query term and returns their IDs"""
    params = {
        "datetype": "pdat",
        "retmode": "json",
        "mindate": PUBMED_MIN_YEAR,
        "maxdate": PUBMED_MAX_YEAR,
        "term": query,
        "retmax": num_of_documents,
    }
    params.update(DEFAULT_PUBMED_PARAMS)  # Ensure default params are included
    try:
        ncbi_resp = call_ncbi_api(ENTEREZ_ESEARCH_URL, params=params)
        return ncbi_resp.json().get("esearchresult", {}).get("idlist", [])
    except Exception as e:
        logger.error(f"Error querying PubMed search term: {e}")
        return []

def query_pubmed_by_pmid(pmid_list: list[str]) -> str:
    """Search for Pubmed documents given the document identifiers

    Args:
        pmid_list: list of Pubmed document ids to search

    Returns:
        the pubmed documents queried by pubmed ids
    """
    params = {"id": ",".join(pmid_list), "rettype": "abstract", "retmode": "xml"}
    ncbi_resp = call_ncbi_api(ENTEREZ_EFETCH_URL, params=params)
    return ncbi_resp.content.decode("utf-8")

# CrewAI Tool Definitions

class PubMedSearchInput(BaseModel):
    """Input parameters for PubMedSearchTool."""
    query: str = Field(..., description="The query term or phrase to search for in PubMed.")
    num_of_documents: int = Field(default=10, description="The maximum number of documents to return.")

class PubMedIDListInput(BaseModel):
    """Schema for a list of PubMed IDs."""
    pmids: List[str] = Field(..., description="A list of PubMed IDs to fetch details for.")

class PubMedSearchByTermTool(BaseTool):
    name: str = "PubMed Search By Term Tool"
    description: str = (
        "Searches PubMed database using search terms for scientific literature. "
        "Returns titles and abstracts of matching articles."
    )
    args_schema: Type[BaseModel] = PubMedSearchInput

    def _run(self, query: str, num_of_documents: int = 10) -> str:
        pmids = query_pubmed_by_term(query, num_of_documents)
        if not pmids:
            return f"No results found for search query: '{query}'"
        return query_pubmed_by_pmid(pmids)
    
class PubMedSearchByPMIDsTool(BaseTool):
    name: str = "PubMed Search By PMIDs"
    description: str = (
        "Searches PubMed database using PMID for scientific literature. "
        "Returns titles and abstracts of matching articles."
    )
    args_schema: Type[BaseModel] = PubMedIDListInput

    def _run(self, pmids: str,) -> str:
        return fetch_pubmed_details(pmids)
    
# tool = PubMedSearchTool()
# ret = tool.run("cancer immunotherapy", num_of_documents=5)
# print(ret)