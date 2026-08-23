from pipecat.services.openai.realtime import events as realtime_events

from src import config


def build_turn_detection():
    if config.TURN_DETECTION == "server_vad":
        overrides = {}
        if config.VAD_THRESHOLD is not None:
            overrides["threshold"] = config.VAD_THRESHOLD
        if config.VAD_SILENCE_MS is not None:
            overrides["silence_duration_ms"] = config.VAD_SILENCE_MS
        return realtime_events.TurnDetection(**overrides)
    return realtime_events.SemanticTurnDetection(eagerness=config.VAD_EAGERNESS)


def build_session_properties(tools):
    return realtime_events.SessionProperties(
        tools=tools,
        audio=realtime_events.AudioConfiguration(
            input=realtime_events.AudioInput(
                transcription=realtime_events.InputAudioTranscription(
                    language=config.TRANSCRIBE_LANGUAGE
                ),
                turn_detection=build_turn_detection(),
            )
        ),
    )


def resolved_turn_detection():
    return build_turn_detection().model_dump(exclude_none=True)
