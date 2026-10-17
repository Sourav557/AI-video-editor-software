"""Worker registry — import workers here so they self-register with the orchestrator."""
from ..orchestrator.queue import orchestrator
from . import transcribe, silence  # noqa: F401

orchestrator.register("transcribe", transcribe.run)
orchestrator.register("silence", silence.run)
