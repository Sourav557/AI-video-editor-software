"""Worker registry — import workers here so they self-register with the orchestrator."""
from ..orchestrator.queue import orchestrator
from . import transcribe, silence, score, caption, export, tts, seo, montage, agent  # noqa: F401

orchestrator.register("transcribe", transcribe.run)
orchestrator.register("silence", silence.run)
orchestrator.register("score", score.run)
orchestrator.register("caption", caption.run)
orchestrator.register("export", export.run)
orchestrator.register("tts", tts.run)
orchestrator.register("seo", seo.run)
orchestrator.register("montage", montage.run)
orchestrator.register("agent", agent.run)
