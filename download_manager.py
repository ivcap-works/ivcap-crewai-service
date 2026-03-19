"""
Download Manager for IVCAP CrewAI Service
Downloads data from IVCAP for a list of context URNs.

For each URN (an aspect URN) the priority is:
  1. If the aspect policy is 'urn:ivcap:policy:ivcap.base.service' (service output)
     → save the aspect content dict as JSON to disk.
  2. Else if 'artifactUrn' is present in the aspect content
     → download the artifact binary and save to disk.
  3. Otherwise (fallback)
     → save the aspect content dict as JSON to disk.

Saved files are placed in the same job-isolated directory structure used by ArtifactManager:
    {IVCAP_RUNS_BASE_DIR}/runs/{job_id}/inputs/
"""

import json
import os
import shutil
from pathlib import Path
from typing import List, Optional

from ivcap_service import getLogger, JobContext
from ivcap_client.api.aspect import aspect_read
from ivcap_client.utils import process_error


logger = getLogger("app.download_manager")

IVCAP_URL = os.environ.get("IVCAP_BASE_URL", "https://develop.ivcap.net")

# Aspects with this policy are outputs from a prior IVCAP service;
# their content is what we want rather than an artifact they may reference.
SERVICE_OUTPUT_POLICY = "urn:ivcap:policy:ivcap.base.service"

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


class DownloadManager:
    """
    Downloads IVCAP data (artifacts or aspect content) for a specific job.

    For each context URN the priority is:
      1. Policy == SERVICE_OUTPUT_POLICY  → save aspect content as JSON (service output).
      2. 'artifactUrn' found in content   → download the artifact binary.
      3. Fallback                         → save aspect content as JSON.

    Directory structure (same as ArtifactManager):
        {IVCAP_RUNS_BASE_DIR}/runs/{job_id}/inputs/

    Usage:
        mgr = DownloadManager(job_context=jobCtxt)
        inputs_dir = mgr.download(["urn:ivcap:aspect:..."])
        # ... use files in inputs_dir ...
        mgr.cleanup()
    """

    def __init__(self, job_context: JobContext):
        self.job_id = job_context.job_id
        self.inputs_dir = Path(
            f"{os.getenv('IVCAP_RUNS_BASE_DIR', '/tmp')}/runs/{self.job_id}/inputs"
        )
        self.ivcap_client = job_context.ivcap

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download(self, context_urns: List[str]) -> Optional[str]:
        """
        Download data for each context URN into the job inputs directory.

        Args:
            context_urns: List of IVCAP aspect URNs.
            ivcap_client: IVCAP client from JobContext.ivcap.

        Returns:
            Path to inputs directory as string, or None if nothing was saved.
        """
        if not context_urns:
            logger.info("No context URNs to download")
            return None

        self.inputs_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created inputs directory: {self.inputs_dir}")

        downloaded_count = 0
        for idx, urn in enumerate(context_urns):
            try:
                saved = self._download_one(urn, idx)
                if saved:
                    downloaded_count += 1
            except Exception as e:
                logger.warning(f"Failed to download {urn}: {e}")

        if downloaded_count == 0:
            logger.error("No URNs successfully downloaded")
            self.cleanup()
            return None

        logger.info(f"Downloaded {downloaded_count}/{len(context_urns)} URNs")
        return str(self.inputs_dir)

    def cleanup(self):
        """Remove all downloaded files for this job."""
        if self.inputs_dir.exists():
            try:
                shutil.rmtree(self.inputs_dir)
                logger.info(f"Cleaned up inputs for job {self.job_id}")
            except Exception as e:
                logger.warning(f"Failed to cleanup inputs: {e}")

    def get_inputs_path(self) -> Optional[str]:
        """Return absolute path to inputs directory if it exists."""
        if self.inputs_dir.exists():
            return str(self.inputs_dir.absolute())
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _download_one(self, urn: str, idx: int) -> bool:
        """
        Download one URN.

        Priority:
          1. Aspect policy == SERVICE_OUTPUT_POLICY → save aspect content as JSON.
          2. content['artifactUrn'] present          → download artifact binary.
          3. Fallback                                → save aspect content as JSON.

        Returns True if a file was saved successfully.
        """
        logger.info("Loading aspect: %s", urn)
        r = aspect_read.sync_detailed(urn, client=self.ivcap_client._client)
        if r.status_code >= 300:
            process_error("aspect", r)

        aspect_rt = r.parsed
        policy = aspect_rt.policy
        content = aspect_rt.content.to_dict() if aspect_rt.content else {}
        content_type = aspect_rt.content_type

        if policy == SERVICE_OUTPUT_POLICY:
            logger.info("  Service output policy detected — saving aspect content")
            return self._save_aspect_content(urn, content, content_type, idx)

        artifact_urn = content.get("artifactUrn") if isinstance(content, dict) else None
        if artifact_urn:
            logger.info("  Found artifactUrn: %s — downloading artifact", artifact_urn)
            return self._save_artifact(artifact_urn, idx)
        return False

    def _save_artifact(self, artifact_urn: str, idx: int) -> bool:
        """Download an artifact binary and save it to disk."""
        artifact = self.ivcap_client.get_artifact(artifact_urn)

        mime_type = artifact.mime_type
        safe_name = self._filename_for_artifact(artifact.name, mime_type, idx)
        file_path = self.inputs_dir / safe_name

        file_obj = artifact.as_file()
        with open(file_path, "wb") as f:
            f.write(file_obj.read())

        logger.info(f"  Saved artifact → {file_path} ({mime_type or 'unknown type'})")
        return True

    def _save_aspect_content(
        self,
        urn: str,
        content: dict,
        content_type: Optional[str],
        idx: int,
    ) -> bool:
        """Serialise aspect content dict to a local file."""
        # Derive a base name from the last segment of the URN
        base_name = urn.rsplit(":", 1)[-1] if urn else f"aspect_{idx}"
        if not base_name:
            base_name = f"aspect_{idx}"

        # Choose extension: honour content_type when available, default to .json
        extension = MIME_TO_EXT.get(content_type or "", ".json")
        if not extension:
            extension = ".json"

        file_name = f"{base_name}{extension}"
        file_path = self.inputs_dir / file_name

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(content, f, indent=2, default=str)

        logger.info(f"  Saved aspect content → {file_path}")
        return True

    def _filename_for_artifact(
        self,
        artifact_name: Optional[str],
        mime_type: Optional[str],
        idx: int,
    ) -> str:
        """Return a safe filename with an appropriate extension for an artifact."""
        safe_name = os.path.basename(artifact_name) if artifact_name else ""

        if not safe_name or safe_name.startswith("."):
            safe_name = f"artifact_{idx}"

        _, current_ext = os.path.splitext(safe_name)
        if not current_ext and mime_type:
            ext = MIME_TO_EXT.get(mime_type, "")
            if ext:
                safe_name = f"{safe_name}{ext}"
                logger.info(f"  Added extension '{ext}' from MIME type '{mime_type}'")
            else:
                logger.warning(f"  Unknown MIME type '{mime_type}' — no extension added")

        return safe_name
