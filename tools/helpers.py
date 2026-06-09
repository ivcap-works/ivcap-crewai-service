from crewai_tools import PDFSearchTool, WebsiteSearchTool
from pydantic import model_validator
from typing_extensions import Self

from ivcap_service import getLogger

from tools.source_ref_rag_adapter import SourceRefRagAdapter

logger = getLogger(__name__)


class _SourceRefAdapterMixin:
    """Mixin for RagTool-based tools that scopes searches to a single source.

    Two things are needed to filter a RagTool search by source:

    1. The adapter must accept a source filter. RagTool builds a plain
       ``CrewAIRagAdapter`` whose ``query()`` ignores metadata, so
       ``_use_source_ref_adapter`` swaps in :class:`SourceRefRagAdapter`, whose
       ``query()`` takes a ``source_ref`` and forwards it as
       ``metadata_filter={"source": source_ref}``.
    2. The ``source_ref`` must actually reach ``adapter.query()``. ``RagTool._run``
       (and the parent tools' ``_run``) only pass ``query``/``similarity_threshold``/
       ``limit`` — they drop the pdf/website. So each tool overrides ``_run`` and
       routes through :meth:`_query_with_source`, which mirrors ``RagTool._run``
       but additionally passes ``source_ref``.

    The mixin exists because the tools it serves extend different parents
    (``PDFSearchTool`` vs ``WebsiteSearchTool``), so a shared base class isn't
    available.
    """

    @model_validator(mode="after")
    def _use_source_ref_adapter(self) -> Self:
        if not isinstance(self.adapter, SourceRefRagAdapter):
            provider_cfg = self._parse_config(self.config)
            self.adapter = SourceRefRagAdapter(
                collection_name=self.collection_name,
                summarize=self.summarize,
                similarity_threshold=self.similarity_threshold,
                limit=self.limit,
                config=provider_cfg,
            )
        return self

    def _query_with_source(
        self,
        query: str,
        source_ref: str | None,
        similarity_threshold: float | None = None,
        limit: int | None = None,
    ) -> str:
        """Run a RagTool query scoped to ``source_ref``.

        Replaces ``RagTool._run`` (same threshold/limit defaulting and
        "Relevant Content:" wrapper) but forwards ``source_ref`` to the adapter
        so the search is restricted to that source. A ``source_ref`` of ``None``
        means no filter (collection-wide search, i.e. base behaviour).
        """
        threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self.similarity_threshold
        )
        result_limit = limit if limit is not None else self.limit
        content = self.adapter.query(
            query,
            similarity_threshold=threshold,
            limit=result_limit,
            source_ref=source_ref,
        )
        return f"Relevant Content:\n{content}"


class ResilientPDFSearchTool(_SourceRefAdapterMixin, PDFSearchTool):
    """
    A resilient version of the PDFSearchTool that catches errors
    and guides the agent instead of crashing the script.

    Queries are scoped to the PDF being searched: the ``pdf`` arg is the value
    stored under the ``"source"`` metadata key on add(), so it is forwarded to
    the adapter to keep results accurate when several PDFs share one collection.
    """

    def _run(
        self,
        query: str,
        pdf: str | None = None,
        similarity_threshold: float | None = None,
        limit: int | None = None,
    ) -> str:
        try:
            logger.info("[🔍 Searching PDF: %s | query: %s]", pdf, query)
            # When bound to a fixed PDF at construction the agent passes only
            # `query`; fall back to the stored pdf in that case.
            source_ref = pdf if pdf is not None else self.pdf
            if pdf is not None:
                self.add(pdf)
            return self._query_with_source(query, source_ref, similarity_threshold, limit)

        except Exception as e:
            error_msg = str(e)
            logger.error("[❌ PDF Search Failed: %s]", error_msg)
            return (
                f"SYSTEM ERROR IN PDF SEARCH: {error_msg}. \n"
                f"THOUGHT GUIDANCE: The search failed. Please rephrase your "
                f"search query, use different keywords, otherwise return the final answer based on the information you have. Do not attempt to search again."
            )


class ResilientWebsiteSearchTool(_SourceRefAdapterMixin, WebsiteSearchTool):
    """
    A resilient version of the WebsiteSearchTool that catches errors
    and guides the agent instead of crashing the script.

    Queries are scoped to the website being searched: the ``website`` arg is the
    value stored under the ``"source"`` metadata key on add(), so it is
    forwarded to the adapter to keep results accurate when several sites share
    one collection.
    """

    def _run(
        self,
        search_query: str,
        website: str | None = None,
        similarity_threshold: float | None = None,
        limit: int | None = None,
    ) -> str:
        try:
            logger.info("[🔍 Searching website: %s | query: %s]", website, search_query)
            if website is not None:
                self.add(website)
            return self._query_with_source(search_query, website, similarity_threshold, limit)

        except Exception as e:
            error_msg = str(e)
            logger.error("[❌ Website Search Failed: %s]", error_msg)
            return (
                f"SYSTEM ERROR IN WEBSITE SEARCH: {error_msg}. \n"
                f"THOUGHT GUIDANCE: The search failed. Please rephrase your "
                f"search query, use different keywords, otherwise return the final answer based on the information you have. Do not attempt to search again."
            )
