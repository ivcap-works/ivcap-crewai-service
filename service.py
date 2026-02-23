"""
IVCAP CrewAI Service
Executes CrewAI crews with artifact support and JWT authentication

Updated: Fixed tool initialization to prevent None values and added artifact download validation
Changes:
- Added ArtifactManager for artifact lifecycle
- Added JWT token extraction (4-path fallback with job_authorization)
- Added LLMFactory integration
- Refactored with helper functions for clean orchestration
- Crew building now uses CrewBuilder for proper task context resolution
- Added planning_llm with JWT authentication to support planning feature
- Added LLM validation test calls to catch authentication issues early
- Fixed JWT extraction to use job_authorization attribute (ivcap-ai-tool v0.7.17+)
- Added task output files: saves each task and final output to runs/{job_id}/outputs/
- Added litellm.drop_params configuration to prevent parameter conflicts
- Added embedder configuration for JWT-authenticated embeddings via LiteLLM proxy
- Set OPENAI environment variables for tools that use OpenAI directly (WebsiteSearchTool)
- Set CREWAI_STORAGE_DIR to job-specific path for complete RAG/memory/knowledge isolation
- Added diagnostic logging for embedder config and RAG tools status
- Added PDFSearchTool registration and import
- Implemented automatic tool injection based on artifact file types (PDF → PDFSearchTool, text → DirectorySearchTool)
- Added knowledge_sources support: previous crew outputs → StringKnowledgeSource → crew-level knowledge
- Fixed Path import shadowing issue (removed duplicate local imports)
- Fixed PDFSearchTool/DirectorySearchTool auto-injection to use correct URN format (lowercase first char)
- Fixed tool factories to never return None (always return valid tool instances with fallbacks)
- Added fail-fast validation: raises RuntimeError when artifact download fails
"""

import datetime
import os
import time
import shutil
from pathlib import Path
from typing import Optional, Union
from dotenv import load_dotenv

# Disable telemetry BEFORE importing CrewAI
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"

# Configure LiteLLM drop_params to prevent parameter conflicts
import litellm
litellm.drop_params = True
litellm.additional_drop_params = ["stop"]
litellm.set_verbose = False  # Set to True for debugging

from pydantic import BaseModel, Field, ConfigDict
from crewai import LLM
from crewai.types.usage_metrics import UsageMetrics
from crewai_tools import DirectoryReadTool, DirectorySearchTool, FileReadTool, PDFSearchTool, SerperDevTool, ScrapeWebsiteTool, WebsiteSearchTool

from ivcap_service import getLogger, Service, JobContext, get_secret
from ivcap_ai_tool import start_tool_server, ToolOptions, ivcap_ai_tool, logging_init
from ivcap_client import IVCAP

from service_types import CrewA, TaskResponse, add_supported_tools
from llm_factory import get_llm_factory
from artifact_manager import ArtifactManager
from ivcap_langgraph_tool import create_langgraph_tool

from tools.search import WebsiteSearchToolWithLinks, SerperDevToolWithLinks
from tools.url_metadata_extractor import URLMetadataExtractor
from tools.reference_validator import ReferenceValidationTool

# Initialize logging
load_dotenv(".env.local")
logging_init("./logging.json")
logger = getLogger("app")

# for local test env, please set the SERPER_API_KEY explicitly
try:
    get_secret("SERPER_API_KEY")
except Exception as e:
    logger.error("failed to load SERPER_API_KEY key, will impact the SERPER search tool functionality %s", e)

# Define IVCAP service metadata
service = Service(
    name="IVCAP CrewAI Service",
    version=os.getenv("VERSION"),
    contact={
        "name": "Sonali Majumdar",
        "email": "sonali.majumdar@data61.csiro.au",
    },
    license={
        "name": "MIT",
        "url": "https://opensource.org/license/MIT",
    },
)

# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class CrewRequest(BaseModel):
    """Request to execute a CrewAI crew."""
    jschema: str = Field("urn:sd-core:schema.crewai.request.1", alias="$schema")
    name: str = Field(description="Name of this crew execution")
    inputs: Optional[dict] = Field(None, description="Input variables for crew")

    # Crew definition (one of these required)
    crew_ref: Optional[str] = Field(
        None,
        description="IVCAP aspect URN referencing crew definition",
        alias="crew-ref"
    )
    crew: Optional[CrewA] = Field(
        None,
        description="Inline crew definition"
    )

    # Optional features
    artifact_urns: Optional[list[str]] = Field(
        None,
        description="IVCAP artifact URNs to download as inputs",
        alias="artifact-urns"
    )
    additional_inputs: Optional[Union[str, list[str]]] = Field(
        None,
        description="Previous crew outputs as markdown (string or list of strings)",
        alias="additional-inputs"
    )
    enable_citations: Optional[bool] = Field(
        False,
        description="Enable citation tracking (experimental)"
    )

    model_config = ConfigDict(populate_by_name=True)


class CrewResponse(BaseModel):
    """Response from crew execution."""
    jschema: str = Field("urn:sd-core:schema.crewai.response.1", alias="$schema")
    answer: str = Field(description="Final crew output")
    crew_name: str = Field(description="Name of executed crew")
    place_holders: list = Field(description="Placeholders used")
    task_responses: list[TaskResponse] = Field(description="Individual task outputs")
    created_at: str = Field(description="Execution timestamp")
    process_time_sec: float = Field(description="CPU time")
    run_time_sec: float = Field(description="Wall clock time")
    token_usage: UsageMetrics = Field(description="LLM token usage")
    citations: Optional[dict] = Field(None, description="Citation report if enabled")


# ============================================================================
# TOOL REGISTRATION
# ============================================================================

add_supported_tools({
    # SerperDevTool - web search (requires SERPER_API_KEY)
    "urn:sd-core:crewai.builtin.serperDevTool":
        lambda _, ctxt: SerperDevToolWithLinks(links_file=f"{ctxt.tmp_dir}/runs/{ctxt.job_id}/researcher_links.json"),

    # ScrapeWebsiteTool - scrape any website during execution
    # Can be initialized with specific URL or dynamically scrape any site
    "urn:sd-core:crewai.builtin.scrapeWebsiteTool":
        lambda _, ctxt: ScrapeWebsiteTool(),

    # DirectoryReadTool - requires inputs_dir (lists files, not semantic search)
    "urn:sd-core:crewai.builtin.directoryReadTool":
        lambda _, ctxt: DirectoryReadTool(directory=ctxt.inputs_dir)
        if ctxt.inputs_dir else DirectoryReadTool(directory="."),

    # DirectorySearchTool - requires inputs_dir (inherits embedder from Crew)
    "urn:sd-core:crewai.builtin.directorySearchTool":
        lambda _, ctxt: DirectorySearchTool(
            directory=ctxt.inputs_dir or "."
            # NO config needed - uses Crew's embedder automatically!
        ),

    # PDFSearchTool - for semantic search within PDF documents (inherits embedder from Crew)
    "urn:sd-core:crewai.builtin.pdfSearchTool":
        lambda _, ctxt: PDFSearchTool(),

    # FileReadTool - requires inputs_dir for base path
    "urn:sd-core:crewai.builtin.fileReadTool":
        lambda _, ctxt: FileReadTool(file_path=ctxt.inputs_dir or "."),

    # WebsiteSearchTool - semantic search with vector embeddings (saves links to file)
    "urn:sd-core:crewai.builtin.websiteSearchTool":
        lambda _, ctxt: WebsiteSearchToolWithLinks(
            config=ctxt.vectordb_config,
            links_file=f"{ctxt.tmp_dir}/runs/{ctxt.job_id}/website_links.json",
            collection_name=f"crew_{ctxt.job_id}",
        ),

    # URL Metadata Extractor - fetches URL and extracts metadata using Claude
    "urn:sd-core:crewai.builtin.urlMetadataExtractor":
        lambda _, ctxt: URLMetadataExtractor(
            jwt_token=ctxt.jwt_token,
            litellm_proxy_url=os.getenv("LITELLM_PROXY_URL"),
            model="gemini-2.5-pro",
            job_folder=f"{ctxt.tmp_dir}/runs/{ctxt.job_id}",
            metadata_file=f"{ctxt.tmp_dir}/runs/{ctxt.job_id}/url_metadata.json",
        ),

    # Reference Validator - validates references against researcher's sources
    "urn:sd-core:crewai.builtin.referenceValidationTool":
        lambda _, ctxt: ReferenceValidationTool(
            url_metadata_extractor=URLMetadataExtractor(
                jwt_token=ctxt.jwt_token,
                litellm_proxy_url=os.getenv("LITELLM_PROXY_URL")
            ),
            default_links_file=f"{ctxt.tmp_dir}/runs/{ctxt.job_id}/researcher_links.json"
        ),

    # IVCAP LangGraph Deep Research Tool - comprehensive web research agent
    "urn:ivcap:service:dcdc770b-d276-5df5-b5b7-babf17fa6eb7":
        create_langgraph_tool,
    "urn:ivcap:langgraph:deep-research":  # Alias for convenience
        create_langgraph_tool,
})


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def crew_wants_artifact_tools(crew_def) -> bool:
    """
    Check if crew intends to use tools for artifact access.

    Returns True if:
    - ANY agent has DirectoryReadTool already defined
    - FIRST agent has "research" or "search" in their goal (case-insensitive)

    Returns False otherwise (crew will use knowledge sources instead)

    Args:
        crew_def: CrewA specification object

    Returns:
        bool: True if crew should use tools, False if should use knowledge sources
    """
    for agent in crew_def.agents:
        # Check for DirectoryReadTool in any agent
        has_directory_tool = any(
            t.id in ["builtin:DirectoryReadTool", "urn:sd-core:crewai.builtin.directoryReadTool"]
            for t in agent.tools
        )
        if has_directory_tool:
            return True

    # Check goal for research/search keywords ONLY in first agent
    if crew_def.agents:
        first_agent = crew_def.agents[0]
        goal_lower = first_agent.goal.lower()
        if "research" in goal_lower or "search" in goal_lower:
            return True

    return False

def get_auth_token(job_ctxt: JobContext) -> Optional[str]:
    """
    Extract JWT token from JobContext.

    Tries multiple paths for maximum compatibility:
    1. job_ctxt.job_authorization (IVCAP v0.7.17+)
    2. job_ctxt.auth_token (older versions)
    3. job_ctxt.headers['Authorization'] (HTTP headers)
    4. job_ctxt.request.headers['Authorization'] (nested request)

    Args:
        job_ctxt: IVCAP job context

    Returns:
        JWT token string without "Bearer " prefix, or None
    """
    # Path 1: job_authorization attribute (ivcap-ai-tool v0.7.17+)
    if hasattr(job_ctxt, 'job_authorization'):
        token = job_ctxt.job_authorization
        logger.debug(f"Path 1 (job_authorization): token={repr(token)}, type={type(token)}, bool={bool(token)}")
        if token:
            # Remove "Bearer " prefix if present
            if isinstance(token, str) and token.startswith('Bearer '):
                logger.info(f"✓ JWT extracted from job_authorization (with Bearer prefix, length: {len(token)-7})")
                return token[7:]
            logger.info(f"✓ JWT extracted from job_authorization (length: {len(str(token))})")
            return token

    # Path 2: Direct auth_token attribute (older versions)
    if hasattr(job_ctxt, 'auth_token'):
        token = job_ctxt.auth_token
        logger.debug(f"Path 2 (auth_token): token={repr(token)}, bool={bool(token)}")
        if token:
            logger.info(f"✓ JWT extracted from auth_token (length: {len(str(token))})")
            return token

    # Path 3: Headers dict
    if hasattr(job_ctxt, 'headers'):
        headers = job_ctxt.headers if isinstance(job_ctxt.headers, dict) else {}
        auth_header = headers.get('Authorization', '')
        logger.debug(f"Path 3 (headers): Authorization={repr(auth_header)}")
        if auth_header.startswith('Bearer '):
            logger.info(f"✓ JWT extracted from headers (length: {len(auth_header)-7})")
            return auth_header[7:]  # Strip "Bearer " prefix

    # Path 4: Nested request object
    if hasattr(job_ctxt, 'request') and hasattr(job_ctxt.request, 'headers'):
        auth_header = job_ctxt.request.headers.get('Authorization', '')
        logger.debug(f"Path 4 (request.headers): Authorization={repr(auth_header)}")
        if auth_header.startswith('Bearer '):
            logger.info(f"✓ JWT extracted from request.headers (length: {len(auth_header)-7})")
            return auth_header[7:]

    logger.warning("✗ No JWT token found in any path (job_authorization, auth_token, headers, request.headers)")
    return None


def load_crew_definition(req: CrewRequest, ivcap:IVCAP) -> CrewA:
    """
    Load crew definition from request.

    Args:
        req: Crew request with either crew_ref or inline crew

    Returns:
        CrewA definition

    Raises:
        ValueError: If no crew definition provided
    """
    if req.crew_ref:
        crew_def = CrewA.from_aspect(req.crew_ref, ivcap)
    elif req.crew:
        crew_def = req.crew
    else:
        raise ValueError("Must provide either 'crew-ref' or 'crew' in request")

    # Use request name if crew doesn't have one
    if not crew_def.name:
        crew_def.name = req.name

    return crew_def


def create_authenticated_llm(
    jwt_token: Optional[str],
    inputs: Optional[dict]
) -> tuple[LLM, LLM, Optional[dict], Optional[str]]:
    """
    Create LLM instances with JWT authentication and embedder configuration.

    Args:
        jwt_token: JWT token from JobContext
        inputs: Request inputs (may contain llm_model override)

    Returns:
        Tuple of (main_llm, planning_llm, embedder_config, litellm_proxy_url)
    """
    factory = get_llm_factory()

    # Check for model override in inputs
    model_override = inputs.get("llm_model") if inputs else None

    llm = factory.create_llm(
        jwt_token=jwt_token,
        model=model_override,
        temperature=0.7,
        max_tokens=4000
    )

    # Create planning LLM (same model, same auth)
    planning_llm = factory.create_llm(
        jwt_token=jwt_token,
        model=model_override,
        temperature=0.7,
        max_tokens=4000
    )

    # Create embedder configuration if using litellm proxy
    embedder_config = None
    if jwt_token and factory.litellm_proxy_url:
        embedder_config = factory.create_embedder_config(jwt_token)
        logger.info("✓ Created embedder configuration for litellm proxy")

    return llm, planning_llm, embedder_config, factory.litellm_proxy_url


# ============================================================================
# MAIN ENDPOINT
# ============================================================================

@ivcap_ai_tool("/", opts=ToolOptions(tags=["CrewAI Runner"]))
async def crew_runner(req: CrewRequest, jobCtxt: JobContext) -> CrewResponse:
    """
    Execute CrewAI crew with artifact support and authentication.

    Workflow:
        1. Extract JWT token from JobContext
        2. Download artifacts (if provided)
        3. Create authenticated LLM
        4. Build crew with task context resolution
        5. Execute crew
        6. Cleanup artifacts
        7. Return response

    Args:
        req: Crew execution request
        jobCtxt: IVCAP job context (injected by decorator)

    Returns:
        Crew execution response with results
    """
    # Initialize managers
    artifact_mgr = ArtifactManager(jobCtxt.job_id)
    citation_mgr = None
    inputs_dir = None

    try:
        # ==================== STEP 1: AUTHENTICATION ====================
        jwt_token = get_auth_token(jobCtxt)

        # DEBUG: Log JobContext attributes to find where token actually is
        logger.debug(f"JobContext attributes: {dir(jobCtxt)}")
        if hasattr(jobCtxt, 'headers'):
            logger.debug(f"JobContext.headers: {jobCtxt.headers}")
        if hasattr(jobCtxt, 'request'):
            logger.debug(f"JobContext.request type: {type(jobCtxt.request)}")
            if hasattr(jobCtxt.request, 'headers'):
                logger.debug(f"JobContext.request.headers: {dict(jobCtxt.request.headers)}")
            if hasattr(jobCtxt.request, '__dict__'):
                logger.debug(f"JobContext.request attributes: {list(jobCtxt.request.__dict__.keys())}")

        # Get base directory from environment (default: /tmp)
        runs_base_dir = os.getenv("IVCAP_RUNS_BASE_DIR", "/tmp")

        if jwt_token:
            logger.info(f"✓ JWT token detected for LLM authentication (length: {len(jwt_token)})")
            os.environ["CREWAI_STORAGE_DIR"] = f"{runs_base_dir}/runs/{jobCtxt.job_id}"
            logger.info(f"✓ Set CREWAI_STORAGE_DIR for complete job isolation: {os.environ['CREWAI_STORAGE_DIR']}")
        else:
            logger.warning("✗ No JWT token found - LLM calls will fall back to direct OpenAI API")
            os.environ["CREWAI_STORAGE_DIR"] = f"{runs_base_dir}/runs/{jobCtxt.job_id}"
            logger.info(f"✓ Set CREWAI_STORAGE_DIR for job isolation (no JWT): {os.environ['CREWAI_STORAGE_DIR']}")

        # ==================== STEP 2: ARTIFACTS ====================
        ivcap = jobCtxt.ivcap
        if req.artifact_urns:
            logger.info(f"Downloading {len(req.artifact_urns)} artifacts...")
            inputs_dir = artifact_mgr.download_artifacts(
                req.artifact_urns,
                ivcap
            )

            if inputs_dir:
                # Inject inputs directory path into crew inputs
                if req.inputs is None:
                    req.inputs = {}
                req.inputs['inputs_directory'] = inputs_dir
                logger.info(f"✓ Artifacts available at: {inputs_dir}")

                # Detect file types and recommend appropriate tools
                inputs_path = Path(inputs_dir)
                pdf_files = list(inputs_path.glob("*.pdf"))
                text_files = list(inputs_path.glob("*.txt")) + list(inputs_path.glob("*.md")) + list(inputs_path.glob("*.csv"))

                if pdf_files:
                    logger.info(f"📄 Detected {len(pdf_files)} PDF file(s) - PDFSearchTool recommended")
                    logger.info(f"   Files: {', '.join([f.name for f in pdf_files[:5]])}")
                if text_files:
                    logger.info(f"📝 Detected {len(text_files)} text file(s) - DirectorySearchTool recommended")
                    logger.info(f"   Files: {', '.join([f.name for f in text_files[:5]])}")
                if not pdf_files and not text_files:
                    logger.warning("⚠ No recognized file types (PDF/TXT/MD/CSV) - DirectoryReadTool can list files")
            else:
                logger.error("Artifact download failed")
                raise RuntimeError(
                    f"Failed to download {len(req.artifact_urns)} artifact(s). "
                    f"Cannot proceed as crew may depend on these files. "
                    f"Check artifact URNs and permissions."
                )

        # ==================== STEP 3: CITATIONS (optional - not implemented) ====================
        # Citation tracking is prepared but not enabled in this version
        # if req.enable_citations:
        #     citation_mgr = setup_citation_manager(jobCtxt.job_id)
        #     logger.info(f"Citation tracking enabled for job {jobCtxt.job_id}")

        # ==================== STEP 4: LOAD CREW ====================
        crew_def = load_crew_definition(req, ivcap)
        logger.info(f"Loaded crew definition: {crew_def.name}")

        # ==================== STEP 4.5: SMART ARTIFACT HANDLING ====================
        artifact_knowledge_sources = []
        if req.artifact_urns and inputs_dir:
            from service_types import ToolA

            inputs_path = Path(inputs_dir)
            pdf_files = list(inputs_path.glob("*.pdf"))
            text_files = list(inputs_path.glob("*.txt")) + list(inputs_path.glob("*.md")) + list(inputs_path.glob("*.csv"))

            # Decide: tools or knowledge sources?
            use_tools = crew_wants_artifact_tools(crew_def)

            if use_tools:
                logger.info("🔧 Crew has DirectoryReadTool or research/search agents - using tool injection")

                # Identify agents that should get tools (have DirectoryReadTool OR research/search in role/goal)
                agents_needing_tools = []
                for agent in crew_def.agents:
                    has_directory_read = any(
                        t.id in ["builtin:DirectoryReadTool", "urn:sd-core:crewai.builtin.directoryReadTool"]
                        for t in agent.tools
                    )
                    role_lower = agent.role.lower()
                    goal_lower = agent.goal.lower()
                    has_research_goal = "research" in role_lower or "search" in role_lower or "research" in goal_lower or "search" in goal_lower

                    if has_directory_read or has_research_goal:
                        agents_needing_tools.append(agent)
                        logger.info(f"  Agent '{agent.name}' qualified for tool injection (has_directory_read={has_directory_read}, has_research_goal={has_research_goal})")

                if not agents_needing_tools:
                    logger.warning("⚠ Tool mode detected but no agents qualified for tool injection")

                # Inject tools into qualified agents
                for agent in agents_needing_tools:
                    has_directory_read = any(
                        t.id in ["builtin:DirectoryReadTool", "urn:sd-core:crewai.builtin.directoryReadTool"]
                        for t in agent.tools
                    )

                    # Inject DirectoryReadTool if not present
                    if not has_directory_read:
                        dir_tool = ToolA(
                            id="urn:sd-core:crewai.builtin.directoryReadTool",
                            name="DirectoryReadTool",
                            description="Lists all files in the inputs directory"
                        )
                        agent.tools.append(dir_tool)
                        logger.info(f"  → Auto-injected DirectoryReadTool into agent '{agent.name}'")

                    # Inject PDFSearchTool if PDFs detected
                    if pdf_files:
                        has_pdf_search = any(
                            t.id in ["builtin:PDFSearchTool", "urn:sd-core:crewai.builtin.pdfSearchTool"]
                            for t in agent.tools
                        )
                        if not has_pdf_search:
                            pdf_tool = ToolA(
                                id="urn:sd-core:crewai.builtin.pdfSearchTool",
                                name="PDFSearchTool",
                                description="Semantic search within PDF documents using RAG/embeddings"
                            )
                            agent.tools.append(pdf_tool)
                            logger.info(f"  → Auto-injected PDFSearchTool into agent '{agent.name}'")

                    # Inject DirectorySearchTool if text files detected
                    if text_files:
                        has_dir_search = any(
                            t.id in ["builtin:DirectorySearchTool", "urn:sd-core:crewai.builtin.directorySearchTool"]
                            for t in agent.tools
                        )
                        if not has_dir_search:
                            text_tool = ToolA(
                                id="urn:sd-core:crewai.builtin.directorySearchTool",
                                name="DirectorySearchTool",
                                description="Semantic search across text-based files using RAG/embeddings"
                            )
                            agent.tools.append(text_tool)
                            logger.info(f"  → Auto-injected DirectorySearchTool into agent '{agent.name}'")

            else:
                logger.info("📚 Crew has no DirectoryReadTool or research/search agents - using knowledge sources")
                from knowledge_processor import create_knowledge_sources_from_artifacts
                try:
                    artifact_knowledge_sources = create_knowledge_sources_from_artifacts(inputs_dir)
                    logger.info(f"✓ Created {len(artifact_knowledge_sources)} artifact knowledge sources")
                    logger.info("  All agents will have automatic RAG access to artifacts")
                except Exception as e:
                    logger.error(f"Failed to create artifact knowledge sources: {e}", exc_info=True)

        # ==================== STEP 5: CREATE LLM ====================
        llm, planning_llm, embedder_config, litellm_proxy_url = create_authenticated_llm(jwt_token, req.inputs)

        # Test LLMs to validate authentication
        logger.info("Testing LLM authentication...")
        try:
            test_response = llm.call(messages=[{"role": "user", "content": "Hello"}])
            logger.info("✓ Main LLM test successful")
            logger.debug(f"  Response: {str(test_response)[:100]}...")
        except Exception as e:
            logger.error(f"✗ Main LLM test failed: {e}")
            raise RuntimeError(f"LLM authentication test failed: {e}") from e

        try:
            planning_test_response = planning_llm.call(messages=[{"role": "user", "content": "Hello"}])
            logger.info("✓ Planning LLM test successful")
            logger.debug(f"  Response: {str(planning_test_response)[:100]}...")
        except Exception as e:
            logger.error(f"✗ Planning LLM test failed: {e}")
            raise RuntimeError(f"Planning LLM authentication test failed: {e}") from e

        # Set OpenAI environment variables for tools that use OpenAI directly
        if jwt_token and litellm_proxy_url:
            os.environ["OPENAI_API_KEY"] = jwt_token
            os.environ["OPENAI_API_BASE"] = litellm_proxy_url
            logger.info(f"✓ Set OpenAI environment for tool compatibility")

        # ==================== STEP 6: PROCESS KNOWLEDGE SOURCES ====================
        knowledge_sources = []

        # Add artifact knowledge sources (if using knowledge source mode)
        if artifact_knowledge_sources:
            knowledge_sources.extend(artifact_knowledge_sources)

        # Process additional-inputs (previous crew outputs)
        if req.additional_inputs:
            logger.info("📚 Processing additional inputs as knowledge sources...")
            from knowledge_processor import create_knowledge_sources_from_inputs
            try:
                additional_sources = create_knowledge_sources_from_inputs(req.additional_inputs)
                knowledge_sources.extend(additional_sources)
                logger.info(f"✓ Created {len(additional_sources)} knowledge sources from additional inputs")
            except Exception as e:
                logger.error(f"Failed to process additional inputs: {e}", exc_info=True)

        if knowledge_sources:
            logger.info(f"📚 Total knowledge sources for crew: {len(knowledge_sources)}")
            if embedder_config:
                logger.info("  Knowledge sources will use JWT-authenticated embedder")
            else:
                logger.warning("  ⚠ Knowledge sources without embedder - may use default OpenAI")

        # ==================== STEP 7: BUILD CREW ====================
        # CrewBuilder handles task context resolution!
        crew = crew_def.as_crew(
            llm=llm,
            job_id=jobCtxt.job_id,
            planning_llm=planning_llm,
            embedder=embedder_config,
            inputs_dir=inputs_dir,
            jwt_token=jwt_token,
            knowledge_sources=knowledge_sources,
            memory=False,
            verbose=False,
            # planning value now comes from crew_spec.planning (defaults to False)
        )

        logger.info(
            f"✓ Crew built: {len(crew.agents)} agents, "
            f"{len(crew.tasks)} tasks"
        )

        # Log embedder and RAG tools status
        if embedder_config:
            embedder_model = embedder_config.get('config', {}).get('model', 'unknown')
            embedder_base = embedder_config.get('config', {}).get('api_base', 'unknown')
            logger.info(f"✓ RAG tools enabled: DirectorySearchTool will index files in {inputs_dir}")
            logger.info(f"  Embedder: model={embedder_model}, api_base={embedder_base}")
        else:
            logger.warning("⚠ RAG tools disabled: No embedder configured")
            logger.warning("  DirectorySearchTool will NOT work without embedder")

        # ==================== STEP 8: EXECUTE ====================
        logger.info(f"Executing crew: {req.name}")
        start_time = (time.process_time(), time.time())

        # Create outputs directory
        outputs_dir = Path(f"{runs_base_dir}/runs/{jobCtxt.job_id}/outputs")
        outputs_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created outputs directory: {outputs_dir}")
        req.inputs["job_id"] = jobCtxt.job_id
        req.inputs["runs_base_dir"] = runs_base_dir
        crew_result = crew.kickoff(req.inputs)

        end_time = (time.process_time(), time.time())
        logger.info(f"✓ Crew execution complete")

        # Save task outputs to individual files
        for i, task_output in enumerate(crew_result.tasks_output):
            task_name = task_output.name or f"task_{i+1}"
            # Sanitize filename
            safe_task_name = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in task_name)
            task_file = outputs_dir / f"{i+1:02d}_{safe_task_name}.md"

            try:
                with open(task_file, 'w', encoding='utf-8') as f:
                    f.write(f"# Task: {task_output.name}\n\n")
                    f.write(f"**Agent:** {task_output.agent}\n\n")
                    f.write(f"**Description:** {task_output.description}\n\n")
                    f.write("---\n\n")
                    f.write(f"{task_output.raw}\n")
                logger.info(f"✓ Saved task output: {task_file.name}")
            except Exception as e:
                logger.warning(f"Failed to save task output {task_name}: {e}")

        # Save final crew output
        final_output_file = outputs_dir / "final_output.md"
        try:
            with open(final_output_file, 'w', encoding='utf-8') as f:
                f.write(f"# {req.name}\n\n")
                f.write(f"**Executed:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"**Duration:** {end_time[1] - start_time[1]:.2f}s\n\n")
                f.write("---\n\n")
                f.write(f"{crew_result.raw}\n")
            logger.info(f"✓ Saved final output: {final_output_file.name}")
        except Exception as e:
            logger.warning(f"Failed to save final output: {e}")

        # ==================== STEP 8: CITATIONS (if enabled) ====================
        citations_report = None
        # Citation tracking not implemented in this version

        # ==================== STEP 9: BUILD RESPONSE ====================
        response = CrewResponse(
            answer=crew_result.raw,
            crew_name=req.name,
            place_holders=[],
            task_responses=[
                TaskResponse.from_task_output(r)
                for r in crew_result.tasks_output
            ],
            created_at=datetime.datetime.now()
                .astimezone()
                .replace(microsecond=0)
                .isoformat(),
            process_time_sec=end_time[0] - start_time[0],
            run_time_sec=end_time[1] - start_time[1],
            token_usage=crew_result.token_usage,
            citations=citations_report
        )

        logger.info(
            f"Response ready: {len(response.answer)} chars, "
            f"{len(response.task_responses)} tasks"
        )

        return response

    finally:
        # ==================== CLEANUP ====================
        # Always cleanup artifacts and temporary files, even on failure
        if inputs_dir:
            artifact_mgr.cleanup()

        # Clean up researcher links file (used for reference validation)
        runs_base_dir = os.getenv("IVCAP_RUNS_BASE_DIR", "/tmp")
        job_dir = Path(f"{runs_base_dir}/runs/{jobCtxt.job_id}/")
        if os.path.exists(job_dir):
            try:
                shutil.rmtree(job_dir)
                logger.info("Contents of directory %s removed successfully.", job_dir)
            except OSError:
                logger.exception("Error when deleting job dir %s", job_dir)


# ============================================================================
# SERVER STARTUP
# ============================================================================

if __name__ == "__main__":
    # Start server (port is configured in pyproject.toml via poetry-plugin-ivcap)
    start_tool_server(service)
