"""
VectorDB configuration for CrewAI tools
Uses ChromaDB directly without embedchain dependency

Updated: 
- Removed embedchain dependency for CrewAI 1.3.0 compatibility
- Fixed provider name from "chroma" to "chromadb" to match CrewAI validation requirements
"""
import os
from pathlib import Path
import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

BASE_DIR = os.getenv("IVCAP_RUNS_BASE_DIR", "/tmp")
def create_vectordb_config(job_id: str, jwt_token) -> dict:
    """
    Create vectordb configuration for CrewAI tools.
    
    Uses ChromaDB with job-isolated storage at runs/{job_id}/
    
    Args:
        job_id: IVCAP job identifier
    
    Returns:
        Configuration dict for CrewAI tools (WebsiteSearchTool, etc.)
    """
    # Create job-specific directory for ChromaDB
    persist_dir = Path(f"{BASE_DIR}/runs/{job_id}")
    persist_dir.mkdir(parents=True, exist_ok=True)
    
    # Create ChromaDB client with persistent storage
    client = chromadb.PersistentClient(path=str(persist_dir))
    embedding_function = OpenAIEmbeddingFunction(api_key=jwt_token, model_name="text-embedding-3-large", api_base=os.getenv("OPENAI_BASE_URL"))
    # Return config format expected by crewai-tools
    config = {
        "vectordb": {
            "provider": "chromadb",
            "config": {
                "client": client,
                "collection_name": f"crew_{job_id}",
                "config": {"embedding_function": embedding_function}
            }
        }
    }
    
    return config