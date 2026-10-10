import asyncio
from types import SimpleNamespace

import httpx
import pytest

from biletbot.api import API


def test_voice_transcription_provider_and_empty_response():
    async def run():
        api = API(SimpleNamespace(openrouter_key="test-key"))
        await api.http.aclose()
        texts = iter(["  Сочи Мальдивы в октябре  ", " "])

        def respond(request):
            assert str(request.url) == "https://openrouter.ai/api/v1/audio/transcriptions"
            assert request.headers["Authorization"] == "Bearer test-key"
            assert b"openai/whisper-large-v3-turbo" in request.content
            assert b"voice.ogg" in request.content
            return httpx.Response(200, json={"text": next(texts)})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            api.http = client
            assert await api.transcribe(b"audio") == "Сочи Мальдивы в октябре"
            with pytest.raises(ValueError, match="распознать"):
                await api.transcribe(b"audio")

    asyncio.run(run())
