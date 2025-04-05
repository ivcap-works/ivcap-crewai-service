import datetime
import os
# Remove when we use our own telemetry
os.environ["OTEL_SDK_DISABLED"] = "true"
import sys
import time
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# Only used for debugging on Max's machine - should not have any negative impact if directories can't be found
this_dir = os.path.dirname(__file__)
src_dir = os.path.abspath(os.path.join(this_dir, "../../ivcap-sdk-python/ivcap-ai-tool/src"))
sys.path.insert(0, src_dir)

from fastapi import FastAPI
from crewai import LLM
from crewai_tools import SerperDevTool, WebsiteSearchTool, DirectoryReadTool, FileReadTool
from crewai.types.usage_metrics import UsageMetrics
import argparse
from dotenv import load_dotenv

from ivcap_ai_tool.builder import ToolOptions, add_tool_api_route
from ivcap_ai_tool.server import start_tool_server

from ivcap_fastapi import getLogger, logging_init
from service_types import CrewA, TaskResponse, add_supported_tools

logging_init()
logger = getLogger("app")

# Load environment variables from the .env file
load_dotenv()

logger = getLogger("app")

title = "CrewAI Agent Runner"
summary = "Executes queries or chats with the CrewAI agent framework."
description = """
>>> A lot more usefule information here.
"""

class CrewRequest(BaseModel):
    jschema: str = Field("urn:sd-core:schema.crewai.request.1", alias="$schema")
    name: Optional[str] = Field(None, description="Name of the crew conversation.")
    inputs: Optional[Dict[str, str]] = Field(None, description="List of placeholders to be filled into the Crew definition.")
    crew_ref: Optional[str] = Field(None, description="Reference to a Crew definition.", alias="crew-ref")
    crew: Optional[CrewA] = Field(None, description="Crew definition to be executed.")

    model_config = ConfigDict(populate_by_name=True) # Allow using `crew_ref`

class CrewResponse(BaseModel):
    jschema: str = Field("urn:sd:schema:icrew.answer.2", alias="$schema")
    answer: str
    crew_name: str
    place_holders: List[str] = Field([], description="list of placeholders inserted into crew's template")
    task_responses: List[TaskResponse]


    created_at: str = Field(description="time this answer was created ISO")
    process_time_sec: float
    run_time_sec: float
    token_usage: UsageMetrics = Field(description="tokens used while executing this crew")

app = FastAPI(
    title=title,
    description=description,
    summary=summary,
    version=os.environ.get("VERSION", "???"),
    contact={
        "name": "Max Ott",
        "email": "max.ott@data61.csiro.au",
    },
    docs_url="/docs", # ONLY set when there is no default GET
)

add_supported_tools({
    "urn:sd-core:crewai.builtin.serperDevTool": lambda _, ctxt: SerperDevTool(config=ctxt.vectordb_config),
    "urn:sd-core:crewai.builtin.directoryReadTool": lambda _, ctxt: DirectoryReadTool(directory=ctxt.tmp_dir),
    "urn:sd-core:crewai.builtin.fileReadTool": lambda _, ctxt: FileReadTool(directory=ctxt.tmp_dir),
    "urn:sd-core:crewai.builtin.websiteSearchTool": lambda _, ctxt: WebsiteSearchTool(config=ctxt.vectordb_config),
})

async def crew_runner(req: CrewRequest) -> CrewResponse:
    """Provides the ability to request a crew of agents to execute
    their plan on a CrewAI runtime."""

    if req.crew_ref:
        crewDef = CrewA.from_aspect(req.crew_ref)
    else:
        crewDef = req.crew
    if not crewDef:
        raise ValueError("No crew definition provided.")

    llm = LLM(model="gpt-4o", api_key=os.getenv("OPENAI_API_KEY"))
    crew = crewDef.as_crew(llm=llm, memory=False, verbose=False, planning=True)

    logger.info(f"processing crew '{req.name}'")
    try:
        # (crew, ctxt, template) = crew_from_file(crew_fd, inputs, log_fd)
        start_time = (time.process_time(), time.time())
        cres = crew.kickoff(req.inputs)
        # with redirect_stdout(log_fd):
        #     answer = crew.kickoff(inputs)
        end_time = (time.process_time(), time.time())
    except Exception as e:
        logger.error(f"Error: {e}")
        raise e

    resp = CrewResponse(
        answer=cres.raw,
        crew_name=req.name,
        place_holders=[],
        task_responses=[TaskResponse.from_task_output(r) for r in cres.tasks_output],

        created_at=datetime.datetime.now().astimezone().replace(microsecond=0).isoformat(),
        process_time_sec=end_time[0] - start_time[0],
        run_time_sec=end_time[1] - start_time[1],

        token_usage=cres.token_usage
    )
    return resp

add_tool_api_route(app, "/", crew_runner, opts=ToolOptions(tags=["ReAct Agent"], service_id="/"))

def service_args(parser: argparse.ArgumentParser) -> argparse.Namespace:
    parser.add_argument('--litellm-proxy', type=str, help='Address of the the LiteLlmProxy')
    #parser.add_argument('--tmp-dir', type=str, help=f"The 'scratch' directory to use for temporary files [{tmp_dir_prefix}]")
    #parser.add_argument('--testing', action="store_true", help='Add tools for testing (testing.py)')
    args = parser.parse_args()

    if args.litellm_proxy != None:
        os.setenv("LITELLM_PROXY", args.litellm_proxy)


    return args

if __name__ == "__main__":
    start_tool_server(app, crew_runner, custom_args=service_args)
