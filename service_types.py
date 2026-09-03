"""
Service Type Definitions for IVCAP CrewAI Service
Defines Pydantic models for crew specifications, agents, tasks, and tools

Updated: Added tool filtering logic to gracefully handle missing artifacts
Changes:
- Added tool filtering in as_crew_agent() to skip artifact-dependent tools when no inputs_dir
- Tools that require artifacts are silently filtered when artifacts are not provided
- Prevents None tool values that would cause agent creation to fail
"""

from dataclasses import dataclass
import os
from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple, Type, Union

from urllib.parse import urlencode, urljoin
import requests
from pydantic import Field, BaseModel
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tasks import TaskOutput
from crewai.tools.base_tool import BaseTool

from ivcap_client import IVCAP
from ivcap_tool import ivcap_tool_test
from ivcap_service import JobContext, getLogger
from skills.utils import Skill, SkillManager
from vectordb import create_vectordb_config

from events import EventListener
EventListener()
logger = getLogger(__name__)

IVCAP_BASE_URL = os.environ.get("IVCAP_BASE_URL", "http://ivcap.local")
AGENT_MAX_EXECUTION_TIME = int(os.environ.get("AGENT_MAX_EXECUTION_TIME", 300))

@dataclass
class Context():
    """
    Runtime context for crew/agent/task building.
    Passed through the building pipeline to provide:
    - VectorDB configuration for tools
    - Job ID for isolation
    - Optional artifacts directory
    - Optional JWT for authentication
    - Optional LLM factory for custom models

    Updated: Added job_id and optional fields for artifact/JWT support
    Updated: tmp_dir now configurable via IVCAP_RUNS_BASE_DIR environment variable (default: /tmp)
    Updated: Added run_dir - the job's writable working directory. Distinct from
             inputs_dir: run_dir always exists and is where the service writes
             (skills/, outputs/), while inputs_dir is the optional, read-only
             directory of user-supplied artifacts and is None when none were given.
    """
    vectordb_config: dict
    job_context: JobContext
    tmp_dir: str = None  # Set from IVCAP_RUNS_BASE_DIR environment variable

    # Optional features (backward compatible)
    run_dir: Optional[str] = None
    inputs_dir: Optional[str] = None
    llm_factory: Optional[Any] = None
    citation_manager: Optional[Any] = None
    embedder: Optional[dict] = None
    skill_manager: Optional[Any] = None

    def __post_init__(self):
        """Set tmp_dir from environment variable if not provided"""
        if self.tmp_dir is None:
            self.tmp_dir = os.getenv("IVCAP_RUNS_BASE_DIR", "/tmp")
        # Mirror service.py's job directory so a directly-constructed Context
        # (tests, tooling) still gets a valid writable path.
        if self.run_dir is None:
            self.run_dir = f"{os.getcwd()}/runs/{self.job_context.job_id}"

    @property
    def job_id(self):
        return self.job_context.job_id

    @property
    def jwt_token(self):
        return self.job_context.job_authorization

    def get_skill_manager(self) -> SkillManager:
        """
        Lazily create the job's SkillManager.

        Shared by all agents of a crew so a skill named by several agents is
        only downloaded once (the manager caches per entity URN).
        """
        if self.skill_manager is None:
            self.skill_manager = SkillManager(self.job_context, self.run_dir)
        return self.skill_manager


    def download_skills(self, skill_refs: Optional[List[str]]) -> List[Skill]:
        """
        Download skills from IVCAP into the job's skills directory.

        Each reference is either a bare skill name ('scientific_review_writer_report')
        or a full entity URN ('urn:sd:crewai:crew.skill.scientific_review_writer_report').
        The skill aspect (schema 'urn:sd:schema:crew.skill') carries the URN of the
        artifact holding the skill markdown, which is what gets downloaded.

        Skills that cannot be resolved are logged and skipped rather than failing
        crew construction.
        """
        if not skill_refs:
            return []

        skills = self.get_skill_manager().load_skills(skill_refs)
        logger.info(
            "Downloaded %d/%d skills: %s",
            len(skills), len(skill_refs), [str(s.path) for s in skills],
        )
        return skills


def skills_as_backstory(skills: List[Skill]) -> str:
    """Render the local path of each downloaded skill for the agent's backstory."""
    lines = [
        "## Skills",
        "You have been given the following skill documents on the local file system. "
        "Before starting your work, read each one in full and follow its guidelines.",
        "",
    ]
    for s in skills:
        title = s.name or s.entity.rsplit(".", 1)[-1]
        lines.append(f"- {title}: {s.description or 'no description'}")
        lines.append(f"  path: {s.path}")
    return "\n".join(lines)


supported_tools = {}
def add_supported_tools(tools: dict[str, Callable[['ToolA'], BaseTool]]):
# def add_supported_tools(tools: dict[str, Callable[['ToolA'], Any]]):
    global supported_tools
    supported_tools.update(tools)

class BuiltinWrapper(BaseTool):
    """A wrapper for builtin tools to be used in CrewAI."""

    name: str
    description: str
    args_schema: Type[BaseModel]

    _tool: BaseTool

    def __init__(self, tool: BaseTool):
        super().__init__(
            name = tool.name,
            description = tool.description,
            args_schema = tool.args_schema,
        )
        object.__setattr__(self, "_tool", tool)  # For Pydantic immutability

    def _run(self, **kwargs) -> Any:
        return self._tool._run(**kwargs)

# def init_supported_tools(rel_dir: str):
#     global supported_tools
#     supported_tools = {
#         # "builtin:SerperDevTool": SerperDevTool(),
#         # "builtin:DirectoryReadTool": DirectoryReadTool(directory=rel_dir),
#         # "builtin:FileReadTool": FileReadTool(directory=rel_dir),
#         "builtin:WebsiteSearchTool": BuiltinWrapper(WebsiteSearchTool()),
#     }


class ToolA(BaseModel):
    jschema: str = Field("urn:sd:schema.icrew.tool.1", alias="$schema")
    id: str = Field(description="id of tool, either an IVCAP service urn, or a builtin one")
    name: Optional[str] = Field(None, description="name of tool")
    opts: Optional[dict] = Field({}, description="optional options provided to the tool")
    description: Optional[str] = Field(default="", description="description of tool")

    def as_crew_tool(self, ctxt: Context) -> BaseTool:
        try:
            id = self.id
            t = None
            if id.startswith("builtin:"):
                # legacy support
                n = id.split(":")[1]
                id = "urn:sd-core:crewai.builtin." + n[0].lower() + n[1:]

            # First check if tool is registered in supported_tools
            t = supported_tools.get(id)

            # If not found and it's an IVCAP service, try dynamic loading
            if not t and id.startswith("urn:ivcap:service:"):
                t = ivcap_tool_test(id, **self.opts)

            # If still not found, raise error
            if not t:
                raise ValueError(f"Unsupported tool '{id}'")
            tool = t(self, ctxt)
            return tool
        except Exception as err:
            raise err

class AgentA(BaseModel):
    jschema: str = Field("urn:sd:schema.icrew.agent.1", alias="$schema")
    name: str = Field(description="name of agent")
    role: str = Field(description="role description of this agent")
    goal: str = Field(description="goal description for this agent")
    backstory: str = Field(description="the backstroy of this agent")
    llm: Optional[str] = Field(None, description="Optional LLM for this agent: either a profile name ('low_thinking', 'medium_thinking', 'high_thinking', 'fast_writer') or an explicit model name ('gpt-4o')")
    max_iter: int = Field(15, description="max. number of iternations.")
    verbose: bool = Field(False, description="be verbose")
    memory: bool = Field(False, description="use memory")
    allow_delegation: bool = Field(False, description="allow for delegation to other agents")
    tools: List[ToolA] = Field([], description="list of tools the agent can use")
    llm_configs: Optional[dict]= Field(None, description="Optional additional LLM configuration parameters")
    reasoning: bool = Field(False, description="Whether the agent should use a reasoning process")
    max_reasoning_attempts: int = Field(3, description="Maximum number of reasoning attempts the agent will make before giving up")
    skills: Optional[List[str]] = Field([], description="list of IVCAP skills for this agent, either a skill name ('scientific_review_writer_report') or a full entity urn ('urn:sd:crewai:crew.skill.scientific_review_writer_report')")

    def as_crew_agent(self, ctxt: Context, **kwargs) -> Agent:
        """
        Create Agent with optional custom LLM.

        Updated: Supports per-agent custom LLM models via llm_factory
        Updated: Added tool filtering to skip artifact-dependent tools when no artifacts provided
        Updated: Downloads the agent's IVCAP skills and points the agent at their local paths
        """
        try:
            d = self.model_dump(mode='python')
            
            # Filter tools - skip artifact-dependent tools when no inputs_dir available
            artifact_dependent_tools = {
                "builtin:DirectoryReadTool",
                "urn:sd-core:crewai.builtin.directoryReadTool",
                "builtin:DirectorySearchTool", 
                "urn:sd-core:crewai.builtin.directorySearchTool",
                "builtin:PDFSearchTool",
                "urn:sd-core:crewai.builtin.pdfSearchTool",
                "builtin:FileReadTool",
                "urn:sd-core:crewai.builtin.fileReadTool",
            }
            d["llm"]= kwargs.pop('llm') if 'llm' in kwargs else None
            tools = []
            for t in self.tools:
                # Skip artifact-dependent tools when no inputs_dir available
                if t.id in artifact_dependent_tools and not ctxt.inputs_dir:
                    logger.info(
                        f"Skipping tool {t.name} for agent {self.name} - no artifacts provided"
                    )
                    continue
                
                try:
                    tool = t.as_crew_tool(ctxt)
                    tools.append(tool)
                except Exception as e:
                    import logging
                    logging.getLogger("app.crew_builder").error(
                        f"Failed to initialize tool {t.name} for agent {self.name}: {e}"
                    )
                    raise
            
            d['tools'] = tools
            
            # Per-agent custom LLM. `llm` names either a capability profile
            # ("high_thinking", "fast_writer") or an explicit model ("gpt-4o").
            # A profile supplies its own behaviour (reasoning effort, temperature,
            # output budget) and llm_configs override it; an explicit model keeps
            # the previous generic defaults.
            if self.llm and ctxt.llm_factory and ctxt.jwt_token:
                # An unknown name is not an error: it is a model name, which is how
                # every crew definition predating profiles behaves.
                from llm_factory import get_profile

                try:
                    profile = get_profile(self.llm)
                except ValueError:
                    profile = None

                llm_params = dict(self.llm_configs or {})
                if profile is None:
                    llm_params = {"temperature": 0.7, "max_tokens": 4000} | llm_params

                try:
                    if profile is not None:
                        logger.info(
                            "Creating LLM for agent %s from profile %s (model %s) with overrides %s",
                            self.name, profile.name, profile.model(), llm_params
                        )
                        jwt_token = ctxt.jwt_token.split("Bearer ")[1] if "Bearer " in ctxt.jwt_token else ctxt.jwt_token
                        d["llm"] = ctxt.llm_factory.create_llm_for_profile(
                            profile,
                            jwt_token=jwt_token,
                            **llm_params
                        )
                    # else:
                        # logger.info("Creating custom LLM for agent %s with model %s and params %s", self.name, self.llm, llm_params)
                        # custom_llm = ctxt.llm_factory.create_llm(
                        #     jwt_token=ctxt.jwt_token,
                        #     model=self.llm,
                        #     **llm_params
                        # )
                except Exception as e:
                    logger.warning(
                        f"Failed to create custom LLM for agent {self.name}: {e}. "
                        f"Using crew default."
                    )
                    d.pop('llm', None)
            # else:
                # d.pop('llm', None)  # Use crew's LLM
            if self.skills:
                ctxt.download_skills(self.skills)
                d['skills'] = [ctxt.skill_manager.skills_dir]
            else:
                d.pop('skills')
            d.update(**kwargs)
            d["max_execution_time"]=AGENT_MAX_EXECUTION_TIME
            agent = Agent(**d)
            return agent
        except Exception as err:
            raise err

class TaskA(BaseModel):
    jschema: str = Field("urn:sd:schema.icrew.task.1", alias="$schema")
    name: Optional[str] = Field(default=None)
    description: str = Field(description="description of the task")
    expected_output: str = Field(description="description of the expected output")
    agent: str = Field(description="name of agent to use for this task")
    tools: List[ToolA] = Field([])
    async_execution: Optional[bool] = Field(False)
    context: Optional[List[str]] = Field([])  # String names, not Task objects!

    def as_crew_task(self, agents: Dict[str, Agent], ctxt: Context, **kwargs) -> Task:
        """
        Create Task object WITHOUT resolving context.
        
        Context resolution happens in CrewBuilder (two-pass).
        This method only:
        1. Resolves agent name → Agent object
        2. Converts tools
        3. Creates Task with basic config
        
        CrewBuilder will later set task.context = [Task objects]
        
        Updated: Excludes context field - CrewBuilder handles resolution
        """
        # Get dict representation, excluding context (handled by CrewBuilder)
        d = self.model_dump(mode='python', exclude={'context'})
        
        # Resolve agent reference
        agent_name = d.pop('agent')
        if agent_name not in agents:
            raise ValueError(
                f"Unknown agent '{agent_name}'. "
                f"Available agents: {list(agents.keys())}"
            )
        d['agent'] = agents[agent_name]
        
        # Convert tools
        d['tools'] = [t.as_crew_tool(ctxt) for t in self.tools]
        
        # Apply overrides
        d.update(**kwargs)
        
        # Create Task (context will be set by CrewBuilder)
        task = Task(**d)
        return task

class CrewA(BaseModel):
    @classmethod
    def from_aspect(cls, aspect_urn: str, ivcap:IVCAP) -> 'CrewA':
        """Loads an aspect from crew"""
        ivcap_aspects = list(ivcap.list_aspects(entity=aspect_urn, limit=1))
        if ivcap_aspects:
            aspect = ivcap_aspects[0]
            content = aspect.content
        else:
            raise ValueError(f"Aspect not found. {aspect_urn}")
        content['verbose'] = False # should be set on execution
        agents = []
        for name, a in content.get("agents", {}).items():
            a['name'] = name
            agents.append(a)
        content['agents'] = agents
        crew = cls(**content)
        return crew

    jschema: str = Field("urn:sd:schema.icrew.crew.2", alias="$schema")
    name: Optional[str] = Field(None, description="name of crew")
    placeholders: List[str] = Field(None, description="optional list of placeholders used in goal and backstories")
    tasks: List[TaskA] = Field(description="list of tasks to perform in this crew")
    agents: List[AgentA] = Field(description="list of agents in this crew")
    llm_configs: Optional[dict] = Field(None, description="Optional additional LLM configuration parameters to be used as default for agents without custom LLMs")

    planning: Optional[bool] = Field(
        default=False,
        description="Plan the crew execution and add the plan to the crew.",
    )
    cache: Optional[bool] = Field(True, description="Whether the crew should use a cache to store the results of the tools execution.")
    process: Optional[Process] = Field(Process.sequential, description="The process flow that the crew will follow (e.g., sequential, hierarchical).")
    verbose: Optional[bool] = Field(default=False)
    memory: bool = Field(
        default=False,
        description="Whether the crew should use memory to store memories of it's execution",
    )
    memory_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Configuration for the memory to be used for the crew.",
    )
    max_rpm: Optional[int] = Field(
        default=None,
        description="Maximum number of requests per minute for the crew execution to be respected.",
    )

    def as_crew(
        self,
        llm: LLM,
        job_context: JobContext,
        planning_llm: Optional[LLM] = None,
        embedder: Optional[dict] = None,
        inputs_dir: Optional[str] = None,
        run_dir: Optional[str] = None,
        knowledge_sources: Optional[list] = None,
        **kwargs
    ) -> Crew:
        """
        Build Crew using CrewBuilder for proper task context resolution.
        
        This is the entry point from service.py. It:
        1. Creates Context with all runtime info
        2. Delegates to CrewBuilder for proper task chaining
        3. Returns fully configured Crew
        
        Updated: Uses CrewBuilder for two-pass task context resolution
        Updated: Added embedder parameter for JWT-authenticated embeddings
        Updated: Added knowledge_sources parameter for previous crew outputs
        Updated: Added run_dir - the job's writable working directory
        """
        # Import here to avoid circular dependency
        from llm_factory import get_llm_factory
        from crew_builder import CrewBuilder
        
        job_id = job_context.job_id
        jwt_token = job_context.job_authorization
        # Build context
        ctxt = Context(
            vectordb_config=create_vectordb_config(job_id, jwt_token),
            inputs_dir=inputs_dir,
            run_dir=run_dir,
            llm_factory=get_llm_factory() if jwt_token else None,
            embedder=embedder,
            job_context=job_context,
            citation_manager=None  # Not implemented in this version
        )
        
        # Use CrewBuilder for proper task context resolution
        builder = CrewBuilder(ctxt)
        crew = builder.build_crew(
            crew_spec=self,
            llm=llm,
            job_id=job_id,
            planning_llm=planning_llm,
            embedder=embedder,
            knowledge_sources=knowledge_sources,
            **kwargs
        )
        
        return crew

class TaskResponse(BaseModel):
    jschema: str = Field("urn:sd-core:schema.crewai.taskresponse.1", alias="$schema")
    agent: str
    description: str
    summary: str
    raw: str

    @classmethod
    def from_task_output(cls, to: TaskOutput):
        return cls(
            description=to.description,
            summary=to.summary,
            raw=to.raw,
            agent=to.agent
        )

def load_ivcap_aspect(urn: str) -> any:
    # "GET", "path": "/1/aspects?include-content=false&limit=10&schema=urn"
    base_url = IVCAP_BASE_URL
    params = {
        "schema": "urn:sd:schema:icrew-crew.1",
        "entity": urn,
        "limit": 1,
        "include-content": "true",
    }
    url = urljoin(base_url, "/1/aspects") + "?" + urlencode(params)
    try:
        response = requests.get(url)
        if response.status_code != 200:
            raise Exception(f"fetching crew definition '{urn}' - {response}")

        items = response.json().get("items", [])
        if len(items) != 1:
            raise Exception(f"cannot find crew definition '{urn}'")
        return items[0].get("content")
    except requests.exceptions.RequestException as e:
        print("An error occurred:", e)
