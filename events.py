from crewai.utilities.events import (
    CrewKickoffStartedEvent,
    CrewKickoffCompletedEvent,
    AgentExecutionStartedEvent,
    AgentExecutionCompletedEvent,
    TaskStartedEvent,
    TaskCompletedEvent,
    ToolUsageStartedEvent,
    ToolUsageFinishedEvent,
    ToolUsageErrorEvent,
    LLMCallStartedEvent,
    LLMCallCompletedEvent,
    LLMCallFailedEvent,
)
from crewai.utilities.events.base_event_listener import BaseEventListener

from ivcap_ai_tool import get_event_reporter


class EventListener(BaseEventListener):
    def __init__(self):
        super().__init__()

    def setup_listeners(self, bus):

        @bus.on(CrewKickoffStartedEvent)
        def crew_started(source, event):
            r = get_event_reporter()
            if r: r.custom("CREW_STARTED", {"crew_name": event.crew_name})

        @bus.on(CrewKickoffCompletedEvent)
        def crew_completed(source, event):
            r = get_event_reporter()
            if r: r.custom("CREW_COMPLETED", {"crew_id": event.crew_id, "output": event.output})

        @bus.on(AgentExecutionStartedEvent)
        def agent_started(source, event):
            r = get_event_reporter()
            if r: r.custom("AGENT_STARTED", {"role": event.agent.role, "task": event.task.description})

        @bus.on(AgentExecutionCompletedEvent)
        def agent_completed(source, event):
            r = get_event_reporter()
            if r: r.custom("AGENT_COMPLETED", {"role": event.agent.role, "output": event.output})

        @bus.on(TaskStartedEvent)
        def task_started(source, event):
            r = get_event_reporter()
            if r: r.custom("TASK_STARTED", {"description": event.task.description})

        @bus.on(TaskCompletedEvent)
        def task_completed(source, event):
            r = get_event_reporter()
            if r: r.custom("TASK_COMPLETED", {"description": event.task.description})

        @bus.on(ToolUsageStartedEvent)
        def tool_started(source, event):
            r = get_event_reporter()
            if r: r.tool_call_start(tool_call_id="tbd", tool_call_name=event.tool_name)

        @bus.on(ToolUsageFinishedEvent)
        def tool_finished(source, event):
            r = get_event_reporter()
            if r: r.tool_call_end(tool_call_id="tbd")

        @bus.on(ToolUsageErrorEvent)
        def tool_failed(source, event):
            r = get_event_reporter()
            if r: r.run_error(f"Tool {event.tool_name} failed", code="TOOL_ERROR")

        @bus.on(LLMCallStartedEvent)
        def llm_started(source, event):
            r = get_event_reporter()
            if r: r.text_message_start("llm-call", messages=event.messages)

        @bus.on(LLMCallCompletedEvent)
        def llm_completed(source, event):
            r = get_event_reporter()
            if r:
                r.text_message_content("llm-call", delta=event.output)
                r.text_message_end("llm-call")

        @bus.on(LLMCallFailedEvent)
        def llm_failed(source, event):
            r = get_event_reporter()
            if r: r.run_error("LLM call failed", code="LLM_CALL_FAILED")
