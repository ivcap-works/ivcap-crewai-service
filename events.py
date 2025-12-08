
import json
import threading
import hashlib
from typing import ClassVar, Optional

from crewai.events import (
    CrewKickoffStartedEvent,
    CrewKickoffCompletedEvent,
    AgentExecutionStartedEvent,
    AgentExecutionCompletedEvent,
    TaskStartedEvent,
    TaskCompletedEvent,
    ToolUsageEvent,
    ToolUsageStartedEvent,
    ToolUsageFinishedEvent,
    ToolUsageErrorEvent,
    LLMCallFailedEvent,
    BaseEventListener
)

from ivcap_service import BaseEvent, getLogger
from pydantic import Field

logger = getLogger("app.event")

class _AgentStartedEvent(BaseEvent):
    SCHEMA: ClassVar[str] = "urn:sd-core:schema:crewai.event.agent.started.1"
    id: int = Field(description="ID of agent")
    agent: str = Field(description="Name of agent")
    prompt: str = Field(description="Prompt used by agent")

class _AgentCompletedEvent(BaseEvent):
    SCHEMA: ClassVar[str] = "urn:sd-core:schema:crewai.event.agent.completed.1"
    id: int = Field(description="ID of agent")
    agent: str = Field(description="Name of agent")
    output: str = Field(description="The report of the agent")

class _TaskStartedEvent(BaseEvent):
    SCHEMA: ClassVar[str] = "urn:sd-core:schema:crewai.event.task.started.1"
    id: int = Field(description="ID of task")
    description: str = Field(description="Description of task")
    agent: str = Field(description="Name of agent executing this taks")

class _TaskFinishedEvent(BaseEvent):
    SCHEMA: ClassVar[str] = "urn:sd-core:schema:crewai.event.task.finished.1"
    id: int = Field(description="ID of task")
    output: str = Field(description="The output from this task")
    agent: str = Field(description="Name of agent executing this taks")

class _ToolStartedEvent(BaseEvent):
    SCHEMA: ClassVar[str] = "urn:sd-core:schema:crewai.event.tool.started.1"
    id: int = Field(description="ID of tool execution")
    tool_name: str = Field(description="Name of tool")
    tool_args: str  = Field(description="Arguments to tool")
    agent: str = Field(description="Agent using this tool")

class _ToolFinishedEvent(BaseEvent):
    SCHEMA: ClassVar[str] = "urn:sd-core:schema:crewai.event.tool.finished.1"
    id: int = Field(description="ID of tool execution")
    tool_name: str = Field(description="Name of tool")
    output: str  = Field(description="Result returned by tool")
    agent: str = Field(description="Agent using this tool")

class _ToolFailedEvent(BaseEvent):
    SCHEMA: ClassVar[str] = "urn:sd-core:schema:crewai.event.tool.failed.1"
    id: int = Field(description="ID of tool execution")
    tool_name: str = Field(description="Name of tool")
    error: str  = Field(description="Error reported")

class _LlmCallFailedEvent(BaseEvent):
    SCHEMA: ClassVar[str] = "urn:sd-core:schema:crewai.event.llm.failed.1"
    id: int = Field(description="ID of LLM call")
    error: str  = Field(description="Error reported")
    task: Optional[str] = Field(None, description="Name of task this error occurs in")

from ivcap_ai_tool import (get_event_reporter, get_job_id)

class EventListener(BaseEventListener):
    def __init__(self):
        super().__init__()

    def describe_agent(self, agent):
        """Describe agent for logging (agent is crewai.Agent instance)"""
        return f"agent {agent.id} ({agent.role})"

    def describe_agent_task(self, agent, task):
        """Describe agent+task for logging"""
        return f"{self.describe_agent(agent)} with task '{task.description}'"

    def tool_call_id(self, event: ToolUsageEvent) -> str:
        # It's hard to get a tool_call_id since CrewAI doesn't assign something like this.
        # Instead we'll string together the source_fingerprint, the tool name and its args to try to get as close
        # to a unique identifier as we can so that ToolCallStart and ToolCallEnd can be associated.
        ta = event.tool_args
        if not isinstance(ta, str):
            ta = json.dumps(event.tool_args)
        s = f"{event.tool_name}:{ta}"
        h = hashlib.md5(s.encode('utf-8')).hexdigest()
        return h

    def _id(self, source):
        return source.__hash__()

    def setup_listeners(self, bus):
        # @bus.on(CrewKickoffStartedEvent)
        # def crew_started(source, event: CrewKickoffStartedEvent):
        #     r = get_event_reporter()
        #     # CrewKickoffStarted -> RunStarted
        #     if r: r.run_started(thread_id=str(threading.get_native_id()), run_id=get_job_id())

        # @bus.on(CrewKickoffCompletedEvent)
        # def crew_completed(source, event):
        #     r = get_event_reporter()
        #     # CrewKickoffCompleted -> RunFinished
        #     if r: r.run_finished(thread_id=str(threading.get_native_id()), run_id=get_job_id())

        @bus.on(AgentExecutionStartedEvent)
        def agent_started(source, event: AgentExecutionStartedEvent):
            id = self._id(source)
            logger.info(f"{get_job_id()}: agent {id} started")
            if (r := get_event_reporter()):
                event = _AgentStartedEvent(id=id, agent=event.agent.role, prompt=event.task_prompt)
                r.emit(event)

        @bus.on(AgentExecutionCompletedEvent)
        def agent_completed(source, e):
            id = self._id(source)
            logger.info(f"{get_job_id()}: agent {id} completed")
            if (r := get_event_reporter()):
                event = _AgentCompletedEvent(id=id, agent=e.agent.role, output=e.output)
                r.emit(event)

        @bus.on(TaskStartedEvent)
        def task_started(source, e: _TaskStartedEvent):
            id = self._id(source)
            logger.info(f"{get_job_id()}: task {id} strted")
            if (r := get_event_reporter()):
                task = e.task
                event = _TaskStartedEvent(id=id, description=task.description, agent=task.agent.role)
                r.emit(event)

        @bus.on(TaskCompletedEvent)
        def task_completed(source, e: TaskCompletedEvent):
            id = self._id(source)
            logger.info(f"{get_job_id()}: task {id} completed")
            if (r := get_event_reporter()):
                task = e.task
                output = e.output
                event = _TaskFinishedEvent(id=id, output=output.raw, agent=task.agent.role)
                r.emit(event)

        @bus.on(ToolUsageStartedEvent)
        def tool_started(source, e: ToolUsageStartedEvent):
            id = self._id(source)
            logger.info(f"{get_job_id()}: tool {id} started")
            if (r := get_event_reporter()):
                event = _ToolStartedEvent(id=id, tool_name=e.tool_name, tool_args=e.tool_args, agent=e.agent_role)
                r.emit(event)

        @bus.on(ToolUsageFinishedEvent)
        def tool_finished(source, e: ToolUsageFinishedEvent):
            id = self._id(source)
            logger.info(f"{get_job_id()}: tool {id} finished")
            if (r := get_event_reporter()):
                event = _ToolFinishedEvent(id=id, tool_name=e.tool_name, output=e.output, agent=e.agent_role)
                r.emit(event)

        @bus.on(ToolUsageErrorEvent)
        def tool_failed(source, e: ToolUsageErrorEvent):
            id = self._id(source)
            logger.info(f"{get_job_id()}: tool {id} failed - {e.error}")
            if (r := get_event_reporter()):
                event = _ToolFailedEvent(id=id, tool_name=e.tool_name, error=str(e.error))
                r.emit(event)

        # @bus.on(LLMCallStartedEvent)
        # def llm_started(source, event):
        #     r = get_event_reporter()
        #     # LLMCallStarted -> TextMessageStart
        #     # Unfortunately CrewAI doesn't give LLM calls a unique id, and the source_fingerprint doesn't seem to be set
        #     # for these events either.
        #     # We can't even use a hash of the message(s) sent because these aren't reported in the LLMStreamChunkEvent or LLMCallCompletedEvent.
        #     # The role of "assistant" came out of an error insisting it be this...
        #     if r: r.text_message_start(message_id="?", role="assistant")

        # @bus.on(LLMStreamChunkEvent)
        # def llm_stream_chunk(source, event):
        #     r = get_event_reporter()
        #     # LLMStreamChunkEvent -> TextMessageContent
        #     if r: r.text_message_content(message_id="?", delta=event.chunk)

        # @bus.on(LLMCallCompletedEvent)
        # def llm_completed(source, event):
        #     r = get_event_reporter()
        #     # LLMCallCompleted -> TextMessageEnd
        #     # The response is available in `event.response` but ag_ui doesn't want it.
        #     if r: r.text_message_end(message_id="?")

        @bus.on(LLMCallFailedEvent)
        def llm_failed(source, e: LLMCallFailedEvent):
            id = self._id(source)
            logger.warning(f"{get_job_id()}: llm call failed - {e.error}")
            if (r := get_event_reporter()):
                event = _LlmCallFailedEvent(id=id, task=e.task_name, error=str(e.error))
                r.emit(event)
