import datetime
import os
import sys
import time

import openai

# Only used for debugging on Max's machine - should not have any negative impact if directories can't be found
this_dir = os.path.dirname(__file__)
src_dir = os.path.abspath(os.path.join(this_dir, "../../ivcap-sdk-python/ivcap-ai-tool/src"))
sys.path.insert(0, src_dir)

from service_types import CrewA, CrewResponse, TaskResponse, add_supported_tools

from typing import ClassVar, List, Optional
from fastapi import FastAPI

from pydantic import BaseModel, Field
import argparse
from signal import signal, SIGTERM

from dotenv import load_dotenv

from ivcap_ai_tool.builder import ToolOptions, add_tool_api_route
from ivcap_ai_tool.server import start_tool_server
# from llama_index.core.agent import ReActAgent
# from llama_index.llms.openai import OpenAI

from crewai_tools import SerperDevTool, DirectoryReadTool, FileReadTool, WebsiteSearchTool
from crewai import Agent, Task, Crew, Process, LLM

from ivcap_fastapi import getLogger, logging_init

logging_init()
logger = getLogger("app")

# Load environment variables from the .env file
load_dotenv()

logger = getLogger("app")

#from runner import run_query
# from tool import resolve_tool
# from utils import SchemaModel, StrEnum


title = "LLamaIndex Agent Runner"
summary = "Executes queries or chats with LlamaIndex agents."
description = """
>>> A lot more usefule information here.
"""

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

tmp_dir_prefix = "/tmp"
if os.getenv("TMP_DIR"):
    tmp_dir_prefix = os.getenv("TMP_DIR")

add_supported_tools({
    "urn:sd-core:crewai.builtin.serperDevTool": lambda _: SerperDevTool(),
    # "builtin:DirectoryReadTool": DirectoryReadTool(directory=rel_dir),
    # "builtin:FileReadTool": FileReadTool(directory=rel_dir),
    "urn:sd-core:crewai.builtin.websiteSearchTool": lambda _: WebsiteSearchTool(),
})

def service_args(parser: argparse.ArgumentParser) -> argparse.Namespace:
    parser.add_argument('--litellm-proxy', type=str, help='Address of the the LiteLlmProxy')
    parser.add_argument('--tmp-dir', type=str, help=f"The 'scratch' directory to use for temporary files [{tmp_dir_prefix}]")
    #parser.add_argument('--testing', action="store_true", help='Add tools for testing (testing.py)')

    args = parser.parse_args()

    if args.litellm_proxy != None:
        os.setenv("LITELLM_PROXY", args.litellm_proxy)



    # if args.dump_builtin_ivcap_definitions:
    #     from tool import dump_builtin_ivcap_definitions
    #     dir = args.dump_builtin_ivcap_definitions
    #     dump_builtin_ivcap_definitions(dir)
    #     exit(0)

    # if args.testing:
    #     logger.info(f"Adding testing support defined in 'testing.py'")
    #     import testing  # noqa

    # import builtin_tools # registers all builtin tool

    return args

async def crew_runner(req: CrewA) -> CrewResponse:
    """Provides the ability to request a crew of agents to execute
    their plan on a CrewAI runtime."""

    llm = LLM(model="gpt-4o", api_key=os.getenv("OPENAI_API_KEY"))
    crew = req.as_crew(llm=llm, memory=False, verbose=True)

    logger.info(f"processing crew '{req.name}'")
    try:
        # (crew, ctxt, template) = crew_from_file(crew_fd, inputs, log_fd)
        start_time = (time.process_time(), time.time())
        cres = crew.kickoff({})
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
    # llm = create_openai_client(req.model)
    # tools = [resolve_tool(urn) for urn in req.tools]
    # agent = ReActAgent.from_tools(tools, llm=llm, verbose=False)
    # response = await agent.aquery(req.msg)
    # answer = response.response
    # return ServiceResponse(response=answer, msg=req.msg)

# def create_openai_client(f):
#     base_url = os.getenv("LITELLM_PROXY")
#     if base_url == None:
#         return f()
#     else:
#         return f(base_url=f"{base_url}/v1", api_key="not-needed")

def create_openai_client(model: str) -> openai.AsyncOpenAI:
    base_url = os.getenv("LITELLM_PROXY")
    if base_url == None:
        return openai.AsyncOpenAI()
    else:
        return openai.AsyncOpenAI(api_base=f"{base_url}/v1", api_key="not-needed")

add_tool_api_route(app, "/", crew_runner, opts=ToolOptions(tags=["ReAct Agent"], service_id="/"))

if __name__ == "__main__":

    # def custom_sigterm_handler(signum, frame):
    #     print("Custom SIGTERM received. Preventing shutdown.")
    #     time.sleep(5)

    # shutdown pod cracefully
    # signal(SIGTERM, custom_sigterm_handler)

    import uvicorn

    class MyServer(uvicorn.Server):
        def handle_exit(self, sig: int, frame: any) -> None:
            print(f"Custom SIGTERM received. Delaying shutdown. - {sig}")
            #time.sleep(5)
            super().handle_exit(sig, frame)


    # server = uvicorn.Server(config=uvicorn.Config(app=app, host="0.0.0.0", port=8077))
    # server.handle_exit(SIGTERM, custom_sigterm_handler)

    server = MyServer(config=uvicorn.Config(app=app, host="0.0.0.0", port=8077))

    # Override Uvicorn’s SIGTERM handling
    #signal(SIGTERM, custom_sigterm_handler)

    # Start the server
    server.run()

    #start_tool_server(app, crew_runner, custom_args=service_args)
