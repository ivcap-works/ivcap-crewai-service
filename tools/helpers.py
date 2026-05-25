from crewai_tools import PDFSearchTool, WebsiteSearchTool

from ivcap_service import getLogger

logger = getLogger(__name__)

class ResilientPDFSearchTool(PDFSearchTool):
    """
    A resilient version of the PDFSearchTool that catches errors
    and guides the agent instead of crashing the script.
    """
    def _run(self, *args, **kwargs):
        try:
            logger.info("[🔍 Searching PDF with args: %s]", kwargs)
            # Execute the original tool's logic
            return super()._run(*args, **kwargs)
            
        except Exception as e:
            error_msg = str(e)
            logger.error("[❌ PDF Search Failed: %s]", error_msg)
            
            # Return the error as a string with guidance
            return (
                f"SYSTEM ERROR IN PDF SEARCH: {error_msg}. \n"
                f"THOUGHT GUIDANCE: The search failed. Please rephrase your "
                f"search query, use different keywords, otherwise return the final answer based on the information you have. Do not attempt to search again."
            )
        
class ResilientWebsiteSearchTool(WebsiteSearchTool):
    """
    A resilient version of the WebsiteSearchTool that catches errors
    and guides the agent instead of crashing the script.
    """
    def _run(self, *args, **kwargs):
        try:
            logger.info("[🔍 Searching website with args: %s]", kwargs)
            # Execute the original tool's logic
            return super()._run(*args, **kwargs)
            
        except Exception as e:
            error_msg = str(e)
            logger.error("[❌ Website Search Failed: %s]", error_msg)
            
            # Return the error as a string with guidance
            return (
                f"SYSTEM ERROR IN WEBSITE SEARCH: {error_msg}. \n"
                f"THOUGHT GUIDANCE: The search failed. Please rephrase your "
                f"search query, use different keywords, otherwise return the final answer based on the information you have. Do not attempt to search again."
            )