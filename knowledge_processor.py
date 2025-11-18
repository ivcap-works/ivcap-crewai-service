"""
Knowledge Processor for CrewAI Service
Converts inputs into CrewAI Knowledge Sources:
- additional-inputs: Previous crew outputs (StringKnowledgeSource)
- artifacts: PDF/text files (PDFKnowledgeSource/TextFileKnowledgeSource)

Created: 2025-01-13
Purpose: Enable crews to semantically search previous outputs and artifacts via knowledge_sources
"""

from crewai.knowledge.source.string_knowledge_source import StringKnowledgeSource
from crewai.knowledge.source.pdf_knowledge_source import PDFKnowledgeSource
from crewai.knowledge.source.text_file_knowledge_source import TextFileKnowledgeSource
from pathlib import Path
from typing import List, Union, Optional
import logging

# Use standard logging (will be configured by service.py or test harness)
logger = logging.getLogger("app.knowledge_processor")


def create_knowledge_sources_from_inputs(
    inputs: Union[str, List[str]]
) -> List[StringKnowledgeSource]:
    """
    Convert markdown strings into CrewAI Knowledge sources.
    
    This function takes previous crew outputs (as markdown strings) and creates
    StringKnowledgeSource instances that can be passed to a Crew's knowledge_sources
    parameter. All agents in the crew will automatically have semantic search access
    to these sources via RAG (Retrieval-Augmented Generation).
    
    Args:
        inputs: Single markdown string or list of markdown strings from previous
                crew runs. Each string typically contains research findings, analysis
                results, or other structured output from earlier crews.
    
    Returns:
        List of StringKnowledgeSource instances (one per input string). Empty list
        if inputs is None or empty.
    
    Example:
        >>> previous_research = "# Research Results\\n\\nKey finding: X impacts Y..."
        >>> sources = create_knowledge_sources_from_inputs(previous_research)
        >>> crew = Crew(agents=[...], tasks=[...], knowledge_sources=sources)
        
        >>> multiple_inputs = [
        ...     "# Deep Research Output\\n\\nComprehensive findings...",
        ...     "# Expert Profiles\\n\\nKey experts identified..."
        ... ]
        >>> sources = create_knowledge_sources_from_inputs(multiple_inputs)
    
    Notes:
        - Each source will be chunked, embedded, and stored in ChromaDB automatically
        - The crew's embedder configuration will be used for embeddings
        - Sources are isolated per crew run (no cross-contamination)
        - Metadata is added to each source for tracking and debugging
    """
    if not inputs:
        logger.debug("No additional inputs provided, returning empty list")
        return []
    
    # Normalize to list
    input_list = [inputs] if isinstance(inputs, str) else inputs
    logger.info(f"Processing {len(input_list)} additional input(s) into knowledge sources")
    
    sources = []
    for idx, content in enumerate(input_list, 1):
        if content and content.strip():
            try:
                source = StringKnowledgeSource(
                    content=content,
                    metadata={
                        "source_type": "previous_crew_output",
                        "input_index": idx,
                        "source_name": f"reference_input_{idx}",
                        "content_length": len(content)
                    }
                )
                sources.append(source)
                logger.info(
                    f"✓ Created knowledge source {idx}: "
                    f"{len(content)} chars, "
                    f"{len(content.split())} words"
                )
            except Exception as e:
                logger.error(f"Failed to create knowledge source {idx}: {e}", exc_info=True)
                # Continue processing other inputs even if one fails
        else:
            logger.warning(f"Skipping empty input at index {idx}")
    
    logger.info(f"Successfully created {len(sources)}/{len(input_list)} knowledge source(s)")
    return sources


def create_knowledge_sources_from_artifacts(inputs_dir: str) -> List:
    """
    Convert downloaded artifacts into CrewAI Knowledge sources.
    
    This function takes a directory of downloaded artifacts and creates appropriate
    knowledge source instances based on file types. Agents in the crew will automatically
    have semantic search access to these sources via RAG.
    
    Args:
        inputs_dir: Directory path containing downloaded artifacts (PDFs, text files)
    
    Returns:
        List of knowledge source instances (PDFKnowledgeSource, TextFileKnowledgeSource).
        Empty list if inputs_dir is None or doesn't exist.
    
    Example:
        >>> inputs_dir = "runs/job-123/inputs"  # Contains faw1.pdf, faw2.pdf
        >>> sources = create_knowledge_sources_from_artifacts(inputs_dir)
        >>> crew = Crew(agents=[...], tasks=[...], knowledge_sources=sources)
    
    Notes:
        - PDF files are converted to PDFKnowledgeSource instances
        - Text files (.txt, .md, .csv) are converted to TextFileKnowledgeSource instances
        - Each source will be chunked, embedded, and stored in ChromaDB automatically
        - The crew's embedder configuration will be used for embeddings
        - Sources are isolated per crew run (no cross-contamination)
    """
    if not inputs_dir:
        logger.debug("No inputs directory provided")
        return []
    
    inputs_path = Path(inputs_dir)
    if not inputs_path.exists():
        logger.warning(f"Inputs directory doesn't exist: {inputs_dir}")
        return []
    
    sources = []
    
    # Process PDF files
    pdf_files = list(inputs_path.glob("*.pdf"))
    for pdf_file in pdf_files:
        try:
            source = PDFKnowledgeSource(
                file_path=str(pdf_file),
                metadata={
                    "source_type": "artifact_pdf",
                    "filename": pdf_file.name,
                }
            )
            sources.append(source)
            logger.info(f"✓ PDF knowledge source: {pdf_file.name}")
        except Exception as e:
            logger.error(f"Failed to create PDF knowledge source for {pdf_file.name}: {e}")
    
    # Process text files
    text_extensions = ["*.txt", "*.md", "*.csv"]
    for ext in text_extensions:
        text_files = list(inputs_path.glob(ext))
        for text_file in text_files:
            try:
                source = TextFileKnowledgeSource(
                    file_path=str(text_file),
                    metadata={
                        "source_type": "artifact_text",
                        "filename": text_file.name,
                    }
                )
                sources.append(source)
                logger.info(f"✓ Text knowledge source: {text_file.name}")
            except Exception as e:
                logger.error(f"Failed to create text knowledge source for {text_file.name}: {e}")
    
    logger.info(f"Created {len(sources)} artifact knowledge source(s)")
    return sources

