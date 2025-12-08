"""
Service Type Definitions for IVCAP CrewAI Service
Defines Pydantic models for crew specifications, agents, tasks, and tools

Updated: Added tool filtering logic to gracefully handle missing artifacts
Changes:
- Added tool filtering in as_crew_agent() to skip artifact-dependent tools when no inputs_dir
- Tools that require artifacts are silently filtered when artifacts are not provided
- Prevents None tool values that would cause agent creation to fail
"""

from contextlib import redirect_stdout
from dataclasses import dataclass
import datetime
import json
import logging
import os
import time
import logging
import sys
from functools import reduce

from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple, Type, Union

import sys
from urllib.parse import urlencode, urljoin
import requests
from pydantic import Field, BaseModel
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tasks import TaskOutput
from crewai.tools.base_tool import BaseTool

from dotenv import load_dotenv
#from crewai_tools import SerperDevTool, DirectoryReadTool, FileReadTool, WebsiteSearchTool
from crewai_tools import WebsiteSearchTool
from crewai.types.usage_metrics import UsageMetrics
#from langchain_core.agents import AgentAction, AgentFinish
from ivcap_client import IVCAP
from ivcap_tool import ivcap_tool_test
from vectordb import create_vectordb_config

from events import EventListener
EventListener()

IVCAP_BASE_URL = os.environ.get("IVCAP_BASE_URL", "http://ivcap.local")

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
    """
    vectordb_config: dict
    job_id: str
    tmp_dir: str = "/tmp"
    
    # Optional features (backward compatible)
    inputs_dir: Optional[str] = None
    jwt_token: Optional[str] = None
    llm_factory: Optional[Any] = None
    citation_manager: Optional[Any] = None

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
    llm: Optional[str] = Field(None, description="Optional custom model for this agent")
    max_iter: int = Field(15, description="max. number of iternations.")
    verbose: bool = Field(False, description="be verbose")
    memory: bool = Field(False, description="use memory")
    allow_delegation: bool = Field(False, description="allow for delegation to other agents")
    tools: List[ToolA] = Field([], description="list of tools the agent can use")

    def as_crew_agent(self, ctxt: Context, **kwargs) -> Agent:
        """
        Create Agent with optional custom LLM.
        
        Updated: Supports per-agent custom LLM models via llm_factory
        Updated: Added tool filtering to skip artifact-dependent tools when no artifacts provided
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
            
            tools = []
            for t in self.tools:
                # Skip artifact-dependent tools when no inputs_dir available
                if t.id in artifact_dependent_tools and not ctxt.inputs_dir:
                    import logging
                    logging.getLogger("app.crew_builder").info(
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
            
            # Per-agent custom LLM
            if self.llm and ctxt.llm_factory and ctxt.jwt_token:
                try:
                    custom_llm = ctxt.llm_factory.create_llm(
                        jwt_token=ctxt.jwt_token,
                        model=self.llm,
                        temperature=0.7,
                        max_tokens=4000
                    )
                    d['llm'] = custom_llm
                except Exception as e:
                    import logging
                    logging.warning(
                        f"Failed to create custom LLM for agent {self.name}: {e}. "
                        f"Using crew default."
                    )
                    d.pop('llm', None)
            else:
                d.pop('llm', None)  # Use crew's LLM
            
            d.update(**kwargs)
            a = Agent(**d)
            return a
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
        job_id: str,
        planning_llm: Optional[LLM] = None,
        embedder: Optional[dict] = None,
        inputs_dir: Optional[str] = None,
        jwt_token: Optional[str] = None,
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
        """
        # Import here to avoid circular dependency
        from llm_factory import get_llm_factory
        from crew_builder import CrewBuilder
        
        # Build context
        ctxt = Context(
            vectordb_config=create_vectordb_config(job_id, jwt_token),
            job_id=job_id,
            inputs_dir=inputs_dir,
            jwt_token=jwt_token,
            llm_factory=get_llm_factory() if jwt_token else None,
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
