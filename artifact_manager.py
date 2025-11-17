"""
Artifact Manager for IVCAP CrewAI Service
Handles downloading artifacts to job-specific directories and cleanup.

Created: Fresh implementation for task context chaining feature
Changes: 
- New file - manages artifact lifecycle with job isolation
- Added MIME type to file extension mapping for proper file naming
- Added automatic extension detection from artifact metadata
"""

from pathlib import Path
from typing import List, Optional
import shutil
import os
from ivcap_service import getLogger

logger = getLogger("app.artifacts")

# MIME type to file extension mapping
MIME_TO_EXT = {
    # Documents
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    
    # Text
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "text/html": ".html",
    "text/xml": ".xml",
    
    # Data formats
    "application/json": ".json",
    "application/xml": ".xml",
    "application/yaml": ".yaml",
    "text/yaml": ".yaml",
    
    # Images
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
    
    # Archives
    "application/zip": ".zip",
    "application/x-tar": ".tar",
    "application/gzip": ".gz",
    
    # Code
    "text/x-python": ".py",
    "text/javascript": ".js",
    "application/javascript": ".js",
}


class ArtifactManager:
    """
    Manages artifact lifecycle for a specific job.
    
    Directory structure:
        runs/{job_id}/
            inputs/           # Downloaded artifacts
            chroma.sqlite3    # VectorDB (managed separately)
    
    Usage:
        mgr = ArtifactManager(job_id="urn:ivcap:job:123...")
        inputs_dir = mgr.download_artifacts(["urn:ivcap:artifact:abc"], ivcap_client)
        # ... use artifacts ...
        mgr.cleanup()  # Remove all artifacts
    """
    
    def __init__(self, job_id: str):
        """
        Initialize manager for specific job.
        
        Args:
            job_id: IVCAP job identifier (e.g., "urn:ivcap:job:uuid")
        """
        self.job_id = job_id
        self.base_dir = Path(f"runs/{job_id}")
        self.inputs_dir = self.base_dir / "inputs"
    
    def _get_filename_with_extension(
        self,
        artifact_name: str,
        mime_type: Optional[str],
        fallback_index: int
    ) -> str:
        """
        Determine appropriate filename with correct extension.
        
        Args:
            artifact_name: Original artifact name from IVCAP
            mime_type: MIME type from artifact metadata
            fallback_index: Index for generating fallback name
        
        Returns:
            Sanitized filename with appropriate extension
        
        Example:
            _get_filename_with_extension("faw2", "application/pdf", 0) → "faw2.pdf"
            _get_filename_with_extension("report.pdf", "application/pdf", 0) → "report.pdf"
            _get_filename_with_extension("", "application/pdf", 0) → "artifact_0.pdf"
        """
        # Sanitize the base name
        safe_name = os.path.basename(artifact_name) if artifact_name else ""
        
        # Remove leading dots or use fallback
        if not safe_name or safe_name.startswith('.'):
            safe_name = f"artifact_{fallback_index}"
        
        # Check if name already has an extension
        _, current_ext = os.path.splitext(safe_name)
        
        # If no extension and we have a MIME type, add appropriate extension
        if not current_ext and mime_type:
            extension = MIME_TO_EXT.get(mime_type, "")
            if extension:
                safe_name = f"{safe_name}{extension}"
                logger.info(f"  → Added extension '{extension}' from MIME type '{mime_type}': {safe_name}")
            else:
                logger.warning(f"  → Unknown MIME type '{mime_type}' - no extension added to '{safe_name}'")
        elif not current_ext:
            logger.warning(f"  → No extension and no MIME type for '{safe_name}' - file may not be processable")
        else:
            logger.info(f"  → File already has extension '{current_ext}': {safe_name}")
        
        return safe_name
    
    def download_artifacts(
        self, 
        artifact_urns: List[str], 
        ivcap_client
    ) -> Optional[str]:
        """
        Download artifacts from IVCAP to inputs directory.
        
        Args:
            artifact_urns: List of IVCAP artifact URNs to download
            ivcap_client: IVCAP client from JobContext.ivcap
        
        Returns:
            Path to inputs directory as string, or None if download failed
        
        Raises:
            Exception: If critical download error occurs
        """
        if not artifact_urns:
            logger.info("No artifacts to download")
            return None
        
        # Create inputs directory
        self.inputs_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created inputs directory: {self.inputs_dir}")
        
        try:
            downloaded_count = 0
            
            for urn in artifact_urns:
                try:
                    logger.info(f"Downloading artifact: {urn}")
                    artifact = ivcap_client.get_artifact(urn)
                    
                    # DEBUG: Inspect artifact attributes to find MIME type field
                    logger.info(f"  Artifact attributes: {dir(artifact)}")
                    logger.info(f"  Artifact dict: {artifact.__dict__ if hasattr(artifact, '__dict__') else 'N/A'}")
                    
                    # Try multiple possible MIME type attribute names
                    mime_type = (
                        getattr(artifact, 'mime_type', None) or
                        getattr(artifact, 'mime-type', None) or
                        getattr(artifact, 'mimeType', None) or
                        getattr(artifact, 'content_type', None) or
                        getattr(artifact, 'content-type', None)
                    )
                    
                    # Log artifact metadata at INFO level
                    logger.info(f"  Original name: {artifact.name}")
                    logger.info(f"  MIME type detected: {mime_type or 'NONE FOUND'}")
                    logger.info(f"  Size: {getattr(artifact, 'size', 'unknown')} bytes")
                    
                    # Determine filename with appropriate extension
                    safe_name = self._get_filename_with_extension(
                        artifact.name,
                        mime_type,
                        downloaded_count
                    )
                    logger.info(f"  Saving as: {safe_name}")
                    
                    file_path = self.inputs_dir / safe_name
                    local_artifact = artifact.as_local_file()
                    try:
                        shutil.copy2(local_artifact, file_path)
                    except Exception as exp:
                        logger.exception("Error when copying files %s", exp)
                    # Write artifact content
                    # with open(file_path, 'wb') as f:
                    #     content = artifact.as_file()
                    #     # Handle both file-like objects and bytes
                    #     if hasattr(content, 'read'):
                    #         f.write(content.read())
                    #     else:
                    #         f.write(content)
                    
                    logger.info(f"Downloaded {urn} → {file_path}")
                    downloaded_count += 1
                
                except Exception as e:
                    logger.warning(f"Failed to download {urn}: {e}")
                    # Continue with other artifacts rather than failing completely
                    continue
            
            if downloaded_count == 0:
                logger.error("No artifacts successfully downloaded")
                self.cleanup()
                return None
            
            logger.info(f"Downloaded {downloaded_count}/{len(artifact_urns)} artifacts")
            return str(self.inputs_dir)
        
        except Exception as e:
            logger.error(f"Critical error during artifact download: {e}")
            self.cleanup()
            return None
    
    def cleanup(self):
        """
        Remove all downloaded artifacts for this job.
        Called automatically on job completion or failure.
        """
        if self.inputs_dir.exists():
            try:
                shutil.rmtree(self.inputs_dir)
                logger.info(f"Cleaned up artifacts for job {self.job_id}")
            except Exception as e:
                logger.warning(f"Failed to cleanup artifacts: {e}")
    
    def get_inputs_path(self) -> Optional[str]:
        """
        Get path to inputs directory if it exists.
        
        Returns:
            Absolute path as string, or None if directory doesn't exist
        """
        if self.inputs_dir.exists():
            return str(self.inputs_dir.absolute())
        return None


