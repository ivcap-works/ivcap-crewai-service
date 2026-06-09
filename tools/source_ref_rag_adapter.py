"""RAG adapter that scopes queries to a specific source reference.

``CrewAIRagAdapter`` records the original source of every chunk it stores under
the ``"source"`` metadata key (see ``CrewAIRagAdapter.add`` →
``chunk_metadata["source"] = source_ref``). Its ``query()`` method, however,
never forwards a metadata filter to the underlying vector store, so a search
always spans every source in the collection — even though the client
(``BaseClient.search``) accepts a ``metadata_filter``.

This subclass overrides ``query()`` so a search can be restricted to a single
source. The ``source_ref`` is passed through as
``metadata_filter={"source": source_ref}`` — the same key ``add()`` writes — so
only chunks originating from that source are returned. This keeps results
accurate when several documents share one collection.
"""
from __future__ import annotations

from typing import Any

from crewai.rag.types import SearchResult
from crewai_tools.adapters.crewai_rag_adapter import CrewAIRagAdapter

# Metadata key under which CrewAIRagAdapter.add() records the source reference.
SOURCE_METADATA_KEY = "source"


class SourceRefRagAdapter(CrewAIRagAdapter):
    """CrewAIRagAdapter that can scope queries to a given ``source_ref``.

    The source reference may be set on the instance (``source_ref``, applied to
    every query) or supplied per call to :meth:`query`; a per-call value takes
    precedence. When present it is forwarded to the client as
    ``metadata_filter={"source": source_ref}``; when absent the query behaves
    exactly like the base adapter.
    """

    # source_ref: str | None = None

    def query(
        self,
        question: str,
        similarity_threshold: float | None = None,
        limit: int | None = None,
        source_ref: str | None = None,
    ) -> str:
        """Query the knowledge base, optionally filtered by source reference.

        Args:
            question: The question to ask.
            similarity_threshold: Minimum similarity score for results
                (default: ``self.similarity_threshold``).
            limit: Maximum number of results to return (default: ``self.limit``).
            source_ref: Restrict results to chunks whose ``"source"`` metadata
                equals this value. Overrides the instance-level ``source_ref``.

        Returns:
            Relevant content from the knowledge base, joined by blank lines.
        """
        search_limit = limit if limit is not None else self.limit
        search_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self.similarity_threshold
        )
        if self._client is None:
            raise ValueError("Client is not initialized")

        params = {
            "collection_name": self.collection_name,
            "query": question,
            "limit": search_limit,
            "score_threshold": search_threshold,
        }
        if source_ref:
            params["metadata_filter"] = {SOURCE_METADATA_KEY: source_ref}

        results: list[SearchResult] = self._client.search(**params)

        if not results:
            return "No relevant content found."

        contents: list[str] = []
        for result in results:
            content: str = result.get("content", "")
            if content:
                contents.append(content)

        return "\n\n".join(contents)
