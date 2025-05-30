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

from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple, Union

import sys
from urllib.parse import urlencode, urljoin
import requests
from pydantic import Field, BaseModel
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tasks import TaskOutput
from langchain_core.tools.base import BaseTool

from dotenv import load_dotenv
#from crewai_tools import SerperDevTool, DirectoryReadTool, FileReadTool, WebsiteSearchTool
from crewai_tools import WebsiteSearchTool
from crewai.types.usage_metrics import UsageMetrics
#from langchain_core.agents import AgentAction, AgentFinish

from ivcap_tool import ivcap_tool_test
from vectordb import create_vectordb_config

from events import EventListener
EventListener()

IVCAP_BASE_URL = os.environ.get("IVCAP_BASE_URL", "http://ivcap.local")

@dataclass
class Context():
    vectordb_config: dict
    tmp_dir: str = "/tmp"

supported_tools = {}
def add_supported_tools(tools: dict[str, Callable[['ToolA'], BaseTool]]):
# def add_supported_tools(tools: dict[str, Callable[['ToolA'], Any]]):
    global supported_tools
    supported_tools.update(tools)

def init_supported_tools(rel_dir: str):
    global supported_tools
    supported_tools = {
        # "builtin:SerperDevTool": SerperDevTool(),
        # "builtin:DirectoryReadTool": DirectoryReadTool(directory=rel_dir),
        # "builtin:FileReadTool": FileReadTool(directory=rel_dir),
        "builtin:WebsiteSearchTool": WebsiteSearchTool(),
    }


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

            if id.startswith("urn:sd-core:crewai.builtin."):
                t = supported_tools.get(id)
            elif id.startswith("urn:ivcap:service:"):
                t = ivcap_tool_test(id, **self.opts)
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
    llm: str = Field(None, description="name of LLM to use for this agent")
    max_iter: int = Field(15, description="max. number of iternations.")
    verbose: bool = Field(False, description="be verbose")
    memory: bool = Field(False, description="use memory")
    allow_delegation: bool = Field(False, description="allow for delegation to other agents")
    tools: List[ToolA] = Field([], description="list of tools the agent can use")

    def as_crew_agent(self, ctxt: Context, **kwargs) -> Agent:

        try:
            d = self.model_dump(mode='python')
            d['tools'] = [t.as_crew_tool(ctxt) for t in self.tools]
            #d['verbose'] = True
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
    context: Optional[List[str]] = Field([])

    def as_crew_task(self, agents: list[Agent], ctxt: Context, **kwargs) -> Task:
        d = self.model_dump(mode='python')
        an = d.get('agent', None)
        agent = agents.get(an, None)
        if agent:
            d['agent'] = agent
        else:
            raise ValueError(f"unknown agent '{an}'")
        d['tools'] = [t.as_crew_tool(ctxt) for t in self.tools]
        d.update(**kwargs)
        t = Task(**d)
        return t

class CrewA(BaseModel):
    @classmethod
    def from_aspect(cls, aspect_urn: str) -> 'CrewA':
        content = load_ivcap_aspect(aspect_urn)
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

    def as_crew(self, llm: LLM, **kwargs) -> Crew:
        ctxt = Context(vectordb_config=create_vectordb_config())
        agents = {}
        for a in self.agents: agents[a.name] = a.as_crew_agent(llm=llm, ctxt=ctxt)
        tasks = [t.as_crew_task(agents, ctxt=ctxt) for t in self.tasks]

        # result = {}
        # def step_callback(a: Union[AgentFinish, List[Tuple[AgentAction, str]]]):
        #     if isinstance(a, list):
        #         for (aa, s) in a:
        #             if isinstance(aa, AgentAction):
        #                 result.append(aa.dict())
        #                 return
        #     if isinstance(a, AgentFinish):
        #         result.append(a.dict())

        d = self.model_dump(mode='python')
        d.update({
            "agents": agents.values(),
            "tasks": tasks,
            "verbose": True,  # 2, # You can set it to 1 or 2 to different logging levels
            # output_log_file=False,
            # "step_callback": step_callback,
            # max_consecutive_auto_reply=3,
            "allow_parallel": True,
            # temperature=0.7,
            # request_timeout=300,
            # hide_output=False,
            "raise_error": True
        })
        d.update(**kwargs)
        return Crew(**d)

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