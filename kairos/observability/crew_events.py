"""Forward actual CrewAI task starts without accumulating listeners between runs."""
import threading
from contextlib import contextmanager

from crewai.events import BaseEventListener, TaskStartedEvent, LLMStreamChunkEvent

_tasks = {}
_buffers = {}
_lock = threading.Lock()


class ResearchEvents(BaseEventListener):
    def setup_listeners(self, bus):
        @bus.on(TaskStartedEvent)
        def started(source, event):
            with _lock:
                target = _tasks.get(str(event.task_id))
            if target:
                callbacks, trace_id, role = target
                callbacks.dispatch("on_research_task_start", role, trace_id)

        @bus.on(LLMStreamChunkEvent)
        def streamed(source, event):
            task_id = str(event.task_id or getattr(event.from_task, "id", ""))
            chunk = event.chunk
            if not isinstance(chunk, str) or not chunk:
                return
            with _lock:
                target = _tasks.get(task_id)
                if not target:
                    return
                _buffers[task_id] = _buffers.get(task_id, "") + chunk
                if len(_buffers[task_id]) < 100:
                    return
                text = _buffers.pop(task_id)
            callbacks, trace_id, role = target
            callbacks.dispatch("on_research_stream", role, task_id, text, trace_id)


_listener = ResearchEvents()


@contextmanager
def monitor_tasks(tasks, callbacks, trace_id):
    with _lock:
        for task in tasks:
            _tasks[str(task.id)] = (callbacks, trace_id, task.agent.role)
    try:
        yield
    finally:
        with _lock:
            for task in tasks:
                _tasks.pop(str(task.id), None)
                _buffers.pop(str(task.id), None)
