from crewai_tools import PDFSearchTool, WebsiteSearchTool
from pydantic import model_validator
from typing_extensions import Self

from ivcap_service import getLogger

from llm_factory import get_llm_factory
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

    def _jwt_from_config(self) -> str | None:
        """Pull the JWT the tool was constructed with, if any.

        The tool is built with ``config={"embedding_model": <embedder_config>, ...}``
        (see ``service.py``), and the embedder config carries the job's JWT as its
        ``api_key`` (also in ``default_headers.Authorization``). Reusing it lets the
        query-rewrite LLM authenticate through the LiteLLM proxy exactly like the
        embeddings do. Returns ``None`` when no embedder/JWT was configured.
        """
        cfg = getattr(self, "config", None) or {}
        embedding_model = cfg.get("embedding_model") or {}
        return embedding_model.get("config", {}).get("api_key")

    def _rewrite_query(self, raw_query: str) -> str:
        """Uses the default LLM to convert keywords into a semantic search query.

        The LLM comes from :func:`get_llm_factory` so it inherits the service's
        default model and authentication (LiteLLM proxy / fallback) instead of a
        hard-coded direct OpenAI client. The job's JWT is pulled from the tool's
        embedder config (see :meth:`_jwt_from_config`) so the rewrite call uses
        the same proxy authentication as the embeddings. On any failure the
        original query is returned unchanged so search never breaks because of
        rewriting.
        """
        try:
            jwt_token = self._jwt_from_config()
            llm = get_llm_factory().create_llm(jwt_token=jwt_token, model="gpt-4.1", max_tokens=4000)
            response = llm.call(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a search query optimizer. Convert the user's raw keywords "
                            "into a single, clear, descriptive natural language question or statement "
                            "ideal for semantic vector search in a document. "
                            "Respond ONLY with the optimized query."
                        ),
                    },
                    {"role": "user", "content": raw_query},
                ]
            )
            rewritten = (str(response) if response else "").strip().strip('"')
            logger.info("[🔄 raw query %s, Query rewritten: %s]", raw_query, rewritten)
            return rewritten or raw_query
        except Exception as e:
            # Fallback to the original query if the LLM call fails
            logger.warning("[⚠️ Query rewrite failed: %s]", e)
            return raw_query

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
            # query = self._rewrite_query(query)
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
            # search_query = self._rewrite_query(search_query)
            logger.info("[🔍 Searching website: %s | query: %s]", website, search_query)
            if website is not None:
                self.add(website)
            response = self._query_with_source(search_query, website, similarity_threshold, limit)
            logger.info("[✅ Website search successful. Response: %s]", response)
            return response

        except Exception as e:
            error_msg = str(e)
            logger.error("[❌ Website Search Failed: %s]", error_msg)
            return (
                f"SYSTEM ERROR IN WEBSITE SEARCH: {error_msg}. \n"
                f"THOUGHT GUIDANCE: The search failed. Please rephrase your "
                f"search query, use different keywords, otherwise return the final answer based on the information you have. Do not attempt to search again."
            )
