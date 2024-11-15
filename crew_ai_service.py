from contextlib import redirect_stdout
import datetime
import json
import logging
import os
import time
import logging
import sys
from functools import reduce

from typing import Any, Callable, ClassVar, List
sys.path.insert(0, '../../ivcap-sdk-python/ivcap-service-sdk-python/src')
#print(sys.path)

import sys
from pydantic import Field, BaseModel
from crewai import Agent, Task, Crew, Process

from ivcap_sdk_service import ServiceArgs, Aspect
from ivcap_sdk_service import FunctionResponse

from dotenv import load_dotenv
from crewai_tools import SerperDevTool, DirectoryReadTool, FileReadTool, WebsiteSearchTool
from crewai.types.usage_metrics import UsageMetrics

from ivcap_sdk_service import SupportedMimeTypes, ServiceArgs, FunctionService, FunctionRequest
from ivcap_sdk_service import publish_artifact
from ivcap_sdk_service import create_metadata, publish_artifact, get_config
from ivcap_tool import ivcap_tool, ivcap_tool_test

name = "crew-ai-runner"
title = "CrewAI Runner"
description = """An IVCAP service service which takes a CrewAI's 'crew' definition,
 executes it, and returns the results
"""

logger = None # set when called by SDK
load_dotenv()

supported_tools = {}
def init_supported_tools(rel_dir: str):
    global supported_tools
    supported_tools = {
        "builtin:SerperDevTool": SerperDevTool(),
        "builtin:DirectoryReadTool": DirectoryReadTool(directory=rel_dir),
        "builtin:FileReadTool": FileReadTool(directory=rel_dir),
        "builtin:WebsiteSearchTool": WebsiteSearchTool(),
    }

class ToolA(Aspect):
    SCHEMA: ClassVar[str] = "urn:sd:schema:icrew.tool.1"
    id: str = Field(description="id of tool, either an IVCAP service urn, or a builtin one")
    opts: dict = Field({}, description="optional options provided to the tool")

    def as_crew_tool(self) -> Any:
        try:
            id = self.id
            if id.startswith("builtin:"):
                t = supported_tools.get(id)
            elif id.startswith("urn:ivcap:service:"):
                t = ivcap_tool_test(id, **self.opts)
            if not t:
                raise ValueError(f"Unsupported tool '{id}'")
            return t
        except Exception as err:
            raise err

class AgentA(Aspect):
    SCHEMA: ClassVar[str] = "urn:sd:schema:icrew.agent.1"
    name: str = Field(description="name of agent")
    role: str = Field(description="role description of this agent")
    goal: str = Field(description="goal description for this agent")
    backstory: str = Field(description="the backstroy of this agent")
    llm: str = Field(None, description="name of LLM to use for this agent")
    max_iter: int = Field(-1, description="max. number of iternations. -1 .. forever?")
    verbose: bool = Field(False, description="be verbose")
    memory: bool = Field(False, description="use memory")
    allow_delegation: bool = Field(False, description="allow for delegation to other agents")
    tools: List[ToolA] = Field([], description="list of tools the agent can use")

    def as_crew_agent(self, **args) -> Agent:
        try:
            d = self.model_dump(mode='python')
            d['tools'] = [t.as_crew_tool() for t in self.tools]
            a = Agent(**d, **args)
            return a
        except Exception as err:
            raise err

class TaskA(Aspect):
    SCHEMA: ClassVar[str] = "urn:sd:schema:icrew.task.1"
    description: str = Field(description="description of the task")
    expected_output: str = Field(description="description of the expected output")
    agent: str = Field(description="name of agent to use for this task")

    def as_crew_task(self, agents: list[Agent], **args) -> Task:
        d = self.model_dump(mode='python')
        an = d.get('agent', None)
        agent = agents.get(an, None)
        if agent:
            d['agent'] = agent
        else:
            raise ValueError(f"unknown agent '{an}'")
        t = Task(**d, **args)
        return t

class CrewA(FunctionRequest):
    SCHEMA: ClassVar[str] = "urn:sd:schema:icrew.crew.2"
    name: str = Field(description="name of crew")
    placeholders: List[str] = Field(None, description="optional list of placeholders used in goal and backstories")
    tasks: List[TaskA] = Field(description="list of tasks to perform in this crew")
    agents: List[AgentA] = Field(description="list of agents in this crew")

    def as_crew(self, **args) -> Task:
        agents = {}
        for a in self.agents: agents[a.name] = a.as_crew_agent()
        tasks = [t.as_crew_task(agents) for t in self.tasks]
        return Crew(
            agents=agents.values(),
            tasks=tasks
        )

class TaskResponse(BaseModel):
    description: str
    summary: str
    raw: str
    agent: str

class Response(FunctionResponse):
    SCHEMA: ClassVar[str] = "urn:sd:schema:icrew.answer.2"
    answer: str
    crew_name: str
    place_holders: List[str] = Field([], description="list of placeholders inserted into crew's template")
    task_responses: List[TaskResponse]


    created_at: str = Field(description="time this answer was created ISO")
    process_time_sec: float
    run_time_sec: float
    token_usage: UsageMetrics = Field(description="tokens used while executing this crew")

SERVICE = FunctionService(
    name = name,
    title = title,
    description = description,
    contact = {
        "name": "Max Ott",
        "email": "max.ott@data61.csiro.au",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/license/MIT",
    },
    parameters = [],
    request = CrewA,
    response = Response,
)


#load_dotenv()
def service(_: ServiceArgs, svc_logger: logging) -> Callable[[CrewA], Response]:
    global logger
    logger = svc_logger

    out_dir = get_config().OUT_DIR
    os.environ['CREWAI_STORAGE_DIR'] = out_dir
    init_supported_tools(out_dir)

    # NOTE: Integrate with secret-manager
    # azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
    # api_key=os.environ.get("AZURE_OPENAI_KEY")
    os.environ['OPENAI_MODEL_NAME'] = 'gpt-3.5-turbo'

    return process_request

def process_request(req: CrewA) -> Response:
    out_dir = get_config().OUT_DIR

    logger.info(f"processing crew '{req.name}'")
    with open(f"{out_dir}/log.txt", 'w') as log_fd:
        crew = req.as_crew()
        # (crew, ctxt, template) = crew_from_file(crew_fd, inputs, log_fd)
        start_time = (time.process_time(), time.time())
        cres = crew.kickoff({})
        # with redirect_stdout(log_fd):
        #     answer = crew.kickoff(inputs)
        end_time = (time.process_time(), time.time())

    resp = Response(
        answer=cres.raw,
        crew_name=req.name,
        place_holders=[],
        task_responses=[TaskResponse(**r.dict()) for r in cres.tasks_output],

        created_at=datetime.datetime.now().astimezone().replace(microsecond=0).isoformat(),
        process_time_sec=end_time[0] - start_time[0],
        run_time_sec=end_time[1] - start_time[1],

        token_usage=cres.token_usage
    )
    return resp

####
# Entry point
SERVICE.run(service)
