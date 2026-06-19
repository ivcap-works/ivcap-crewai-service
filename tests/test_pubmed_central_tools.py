"""
Tests for the three PubMed Central tools in tools/pubmed.py:

- PubMedCentralSearchByTerm  - search PMC by free-text term
- PubMedCentralSearchByPMCID - look up articles by PMCID
- PubMedCentralSearchByDOI   - resolve DOIs to PMCIDs, then look up articles

All three reach NCBI's E-utilities (and, for DOI, the PMC ID Converter) over HTTP
via tools.pubmed.requests.get. These tests patch that single entry point so no
network access is needed, and dispatch responses by URL:

    esearch.fcgi -> JSON id list        (term search)
    efetch.fcgi  -> XML article set     (article retrieval)
    idconv       -> JSON DOI->PMCID map  (DOI resolution)

For each tool there is one test where the lookup yields article(s) and one where
it yields none, exercising both the "found" and "not found" branches.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Must set env vars before importing any crewai / ivcap modules.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("IVCAP_BASE_URL", "http://localhost:8077")

# Ensure project root is on sys.path so imports resolve correctly.
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A PMC article-set with one article (an article exists).
ARTICLE_XML = (
    b"<pmc-articleset>"
    b"<article><front><article-title>A Real Article</article-title></front></article>"
    b"</pmc-articleset>"
)
# An empty PMC article-set (no article matched the query).
EMPTY_XML = b"<pmc-articleset></pmc-articleset>"


def make_response(*, json_data=None, content=b"", status_code=200):
    """Build a stand-in requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.content = content
    resp.raise_for_status.return_value = None
    return resp


def patch_get(side_effect):
    """Patch tools.pubmed.requests.get with the given side_effect callable."""
    return patch("tools.pubmed.requests.get", MagicMock(side_effect=side_effect))


def called_urls(mock_get):
    """Return the list of URLs passed (positionally) to requests.get."""
    return [c.args[0] for c in mock_get.call_args_list]


# ---------------------------------------------------------------------------
# PubMedCentralSearchByTerm
# ---------------------------------------------------------------------------


def test_term_search_returns_articles_when_found():
    """A term that resolves to PMCIDs returns the efetch article XML."""
    from tools.pubmed import PubMedCentralSearchByTerm

    def fake_get(url, params=None, headers=None, **kwargs):
        if "esearch" in url:
            return make_response(json_data={"esearchresult": {"idlist": ["7092803"]}})
        if "efetch" in url:
            return make_response(content=ARTICLE_XML)
        raise AssertionError(f"unexpected url: {url}")

    with patch_get(fake_get) as mock_get:
        result = PubMedCentralSearchByTerm()._run(query="covid vaccine", article_type="review")

    assert "A Real Article" in result
    # Both stages must have run: search for IDs, then fetch the articles.
    urls = called_urls(mock_get)
    assert any("esearch" in u for u in urls)
    assert any("efetch" in u for u in urls)


def test_term_search_returns_message_when_no_articles():
    """A term that resolves to no PMCIDs returns a 'no results' message and never fetches."""
    from tools.pubmed import PubMedCentralSearchByTerm

    def fake_get(url, params=None, headers=None, **kwargs):
        if "esearch" in url:
            return make_response(json_data={"esearchresult": {"idlist": []}})
        if "efetch" in url:
            raise AssertionError("efetch must not be called when no IDs are found")
        raise AssertionError(f"unexpected url: {url}")

    with patch_get(fake_get) as mock_get:
        result = PubMedCentralSearchByTerm()._run(query="nonsense xyzzy", article_type="review")

    assert "No results found for search query" in result
    # efetch must be skipped entirely.
    assert not any("efetch" in u for u in called_urls(mock_get))


# ---------------------------------------------------------------------------
# PubMedCentralSearchByPMCID
# ---------------------------------------------------------------------------


def test_pmcid_search_returns_articles_when_found():
    """Valid PMCIDs yield the efetch article XML."""
    from tools.pubmed import PubMedCentralSearchByPMCID

    def fake_get(url, params=None, headers=None, **kwargs):
        if "efetch" in url:
            return make_response(content=ARTICLE_XML)
        raise AssertionError(f"unexpected url: {url}")

    with patch_get(fake_get):
        result = PubMedCentralSearchByPMCID()._run(pmcids=["PMC7092803"], article_type="research")

    assert "A Real Article" in result


def test_pmcid_search_returns_no_article_when_not_found():
    """PMCIDs that match nothing of the requested type yield an empty article set."""
    from tools.pubmed import PubMedCentralSearchByPMCID

    def fake_get(url, params=None, headers=None, **kwargs):
        if "efetch" in url:
            return make_response(content=EMPTY_XML)
        raise AssertionError(f"unexpected url: {url}")

    with patch_get(fake_get):
        result = PubMedCentralSearchByPMCID()._run(pmcids=["PMC9999999"], article_type="review")

    assert "<article>" not in result and "<article " not in result


def test_pmcid_search_returns_message_for_no_ids():
    """No PMCIDs supplied returns an explanatory message and makes no HTTP call."""
    from tools.pubmed import PubMedCentralSearchByPMCID

    def fake_get(url, params=None, headers=None, **kwargs):
        raise AssertionError("no request should be made for an empty PMCID list")

    with patch_get(fake_get) as mock_get:
        result = PubMedCentralSearchByPMCID()._run(pmcids=[], article_type="review")

    assert isinstance(result, str)
    assert "No PubMed Central IDs provided" in result
    assert called_urls(mock_get) == []


# ---------------------------------------------------------------------------
# PubMedCentralSearchByDOI
# ---------------------------------------------------------------------------


def test_doi_search_returns_articles_when_resolved():
    """A DOI is resolved to a PMCID, then the article XML is fetched."""
    from tools.pubmed import PubMedCentralSearchByDOI

    def fake_get(url, params=None, headers=None, **kwargs):
        if "idconv" in url:
            return make_response(json_data={"records": [{"pmcid": "PMC7092803"}]})
        if "efetch" in url:
            return make_response(content=ARTICLE_XML)
        raise AssertionError(f"unexpected url: {url}")

    with patch_get(fake_get) as mock_get:
        result = PubMedCentralSearchByDOI()._run(
            dois=["10.1016/S0140-6736(03)14630-2"], article_type="research"
        )

    assert "A Real Article" in result
    # DOI resolution must precede article retrieval.
    urls = called_urls(mock_get)
    assert any("idconv" in u for u in urls)
    assert any("efetch" in u for u in urls)


def test_doi_search_returns_message_when_doi_unresolvable():
    """A DOI with no PMCID returns a 'not found' message and never fetches articles."""
    from tools.pubmed import PubMedCentralSearchByDOI

    def fake_get(url, params=None, headers=None, **kwargs):
        if "idconv" in url:
            # ID converter found a record but it has no PMCID (not in PMC).
            return make_response(json_data={"records": [{"pmid": "12345"}]})
        if "efetch" in url:
            raise AssertionError("efetch must not be called when no DOI resolves to a PMCID")
        raise AssertionError(f"unexpected url: {url}")

    with patch_get(fake_get) as mock_get:
        result = PubMedCentralSearchByDOI()._run(dois=["10.0/does-not-exist"], article_type="review")

    assert "No PubMed Central articles found for DOIs" in result
    assert "10.0/does-not-exist" in result
    assert not any("efetch" in u for u in called_urls(mock_get))
