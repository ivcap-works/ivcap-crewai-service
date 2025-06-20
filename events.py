import json
import threading

from crewai.utilities.events import (
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
    LLMCallStartedEvent,
    LLMStreamChunkEvent,
    LLMCallCompletedEvent,
    LLMCallFailedEvent,
)
from crewai.utilities.events.base_event_listener import BaseEventListener
from crewai.agents.agent_builder.base_agent import BaseAgent


from ivcap_ai_tool import (get_event_reporter, get_job_id)


class EventListener(BaseEventListener):
    def __init__(self):
        super().__init__()

    def describe_agent(self, agent: BaseAgent):
        return f"agent {agent.id} ({agent.role})"

    def describe_agent_task(self, agent: BaseAgent, task):
        return f"{self.describe_agent(agent)} with task '{task.description}'"

    def tool_call_id(self, event: ToolUsageEvent) -> str:
        # It's hard to get a tool_call_id since CrewAI doesn't assign something like this.
        # Instead we'll string together the source_fingerprint, the tool name and its args to try to get as close
        # to a unique identifier as we can so that ToolCallStart and ToolCallEnd can be associated.
        return f"{event.source_fingerprint}:{event.tool_name}({json.dumps(event.tool_args)})"

    def setup_listeners(self, bus):

        # The general task in the event handlers below is to translate
        # [CrewAI events](https://docs.crewai.com/concepts/event-listener#available-event-types)
        # into [ag_ui events](https://docs.ag-ui.com/concepts/events).
        # Unfortunately there is a bit of a mismatch here, since ag_ui
        # expects that a run is of a single agent: "These events represent the lifecycle of an agent run.",
        # whereas a CrewAI crew run consists of multiple agents being run.
        # We have chosen to translate the whole crew being run as an ag_ui 'run'.
        # Individual agents being run then translate to ag_ui 'steps'.

        # TODO: Can the repeated calls to `get_event_reporter()` be replaced with a single member variable?
        # It would de-clutter the code but does get_event_reporter() return the same object throughout?

        # Note: We have chosen to populate `raw_event` arguments with calls to `event.to_json()`, (from `CrewBaseEvent`), which
        # excludes the `crew` field but otherwise converts the
        # python object to json.
        # This may or may not be the right call.

        @bus.on(CrewKickoffStartedEvent)
        def crew_started(source, event: CrewKickoffStartedEvent):
            r = get_event_reporter()
            # CrewKickoffStarted -> RunStarted
            if r: r.run_started(thread_id=str(threading.get_native_id()), run_id=get_job_id(), raw_event=event.to_json())

        @bus.on(CrewKickoffCompletedEvent)
        def crew_completed(source, event):
            r = get_event_reporter()
            # CrewKickoffCompleted -> RunFinished
            if r: r.run_finished(thread_id=str(threading.get_native_id()), run_id=get_job_id(), raw_event=event.to_json())

        @bus.on(AgentExecutionStartedEvent)
        def agent_started(source, event):
            r = get_event_reporter()
            # AgentExecutionStarted -> StepStarted
            if r: r.step_started(step_name=self.describe_agent_task(event.agent, event.task), raw_event=event.to_json())

        @bus.on(AgentExecutionCompletedEvent)
        def agent_completed(source, event):
            r = get_event_reporter()
            # AgentExecutionCompleted -> StepFinished
            if r: r.step_finished(step_name=self.describe_agent_task(event.agent, event.task), raw_event=event.to_json())

        @bus.on(TaskStartedEvent)
        def task_started(source, event):
            r = get_event_reporter()
            # TaskStarted -> StepStarted
            if r: r.step_started(step_name=f"{event.task.name}: {event.task.description}", raw_event=event.to_json())

        @bus.on(TaskCompletedEvent)
        def task_completed(source, event):
            r = get_event_reporter()
            # TaskCompleted -> StepFinished
            if r: r.step_finished(step_name=f"{event.task.name}: {event.task.description}", raw_event=event.to_json())

        @bus.on(ToolUsageStartedEvent)
        def tool_started(source, event):
            r = get_event_reporter()
            # ToolUsageStarted -> ToolCallStart
            if r: r.tool_call_start(tool_call_id=self.tool_call_id(event), tool_call_name=event.tool_name)

        @bus.on(ToolUsageFinishedEvent)
        def tool_finished(source, event):
            r = get_event_reporter()
            # ToolUsageFinished -> ToolCallEnd
            if r: r.tool_call_end(tool_call_id=self.tool_call_id(event), raw_event=event.to_json())

        @bus.on(ToolUsageErrorEvent)
        def tool_failed(source, event):
            r = get_event_reporter()
            # ToolUsageError -> RunError
            if r: r.run_error(f"Tool {event.tool_name} ({self.tool_call_id(event)} failed: '{event.error}'", code="TOOL_ERROR")

        @bus.on(LLMCallStartedEvent)
        def llm_started(source, event):
            r = get_event_reporter()
            # LLMCallStarted -> TextMessageStart
            # Unfortunately CrewAI doesn't give LLM calls a unique id, and the source_fingerprint doesn't seem to be set
            # for these events either.
            # We can't even use a hash of the message(s) sent because these aren't reported in the LLMStreamChunkEvent or LLMCallCompletedEvent.
            # The role of "assistant" came out of an error insisting it be this...
            if r: r.text_message_start(message_id="?", role="assistant", raw_event=event.to_json())

        @bus.on(LLMStreamChunkEvent)
        def llm_stream_chunk(source, event):
            r = get_event_reporter()
            # LLMStreamChunkEvent -> TextMessageContent
            if r: r.text_message_content(message_id="?", delta=event.chunk, raw_event=event.to_json())

        @bus.on(LLMCallCompletedEvent)
        def llm_completed(source, event):
            r = get_event_reporter()
            # LLMCallCompleted -> TextMessageEnd
            # The response is available in `event.response` but ag_ui doesn't want it.
            if r: r.text_message_end(message_id="?", raw_event=event.to_json())

        @bus.on(LLMCallFailedEvent)
        def llm_failed(source, event):
            r = get_event_reporter()
            if r: r.run_error(f"LLM call failed: '{event.error}'", code="LLM_CALL_FAILED")