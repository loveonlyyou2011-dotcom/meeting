import asyncio
import logging
from typing import Awaitable, Callable, Optional

from google.genai import types

from transcribe import client

LIVE_MODEL = "gemini-3.1-flash-live-preview"
SESSION_RECONNECT_SECONDS = 9 * 60  # 15분 세션 한도보다 여유있게 9분마다 선제적으로 재접속

logger = logging.getLogger(__name__)


def _build_config(resumption_handle: Optional[str]) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        # 이 모델은 TEXT만 단독으로는 지원하지 않아 AUDIO로 응답받되, 우리는
        # input_transcription(사용자 발화 전사)만 사용하고 모델의 음성 응답은 버린다.
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        session_resumption=types.SessionResumptionConfig(handle=resumption_handle),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()
        ),
    )


class LiveTranscriber:
    """Gemini Live API 세션을 유지하며 오디오를 흘려보내고 전사 텍스트를 콜백으로 전달한다.

    연결이 끊기거나 시간 제한에 도달하면 session_resumption 핸들로 자동 재접속한다.
    Gemini 쪽 오류는 여기서 흡수하고 상태만 알릴 뿐 예외를 호출자에 전파하지 않는다 —
    실시간 자막이 실패해도 녹음/최종 회의록 파이프라인은 영향받지 않아야 하기 때문이다.
    """

    def __init__(
        self,
        on_text: Callable[[str], Awaitable[None]],
        on_status: Callable[[str], Awaitable[None]],
    ):
        self._on_text = on_text
        self._on_status = on_status
        self._audio_queue: "asyncio.Queue[Optional[bytes]]" = asyncio.Queue()
        self._resumption_handle: Optional[str] = None
        self._stopped = False

    def push_audio(self, pcm_bytes: bytes) -> None:
        if not self._stopped:
            self._audio_queue.put_nowait(pcm_bytes)

    def stop(self) -> None:
        self._stopped = True
        self._audio_queue.put_nowait(None)

    async def run(self) -> None:
        while not self._stopped:
            try:
                await self._run_one_session()
            except Exception:
                logger.exception("Gemini Live 세션 오류, 재접속 시도")
                await self._on_status("실시간 자막 연결 끊김 - 재접속 중")
                await asyncio.sleep(2)

    async def _run_one_session(self) -> None:
        config = _build_config(self._resumption_handle)
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            await self._on_status("연결됨")
            send_task = asyncio.create_task(self._send_loop(session))
            recv_task = asyncio.create_task(self._recv_loop(session))
            deadline_task = asyncio.create_task(asyncio.sleep(SESSION_RECONNECT_SECONDS))
            try:
                await asyncio.wait(
                    {send_task, recv_task, deadline_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                for task in (send_task, recv_task, deadline_task):
                    task.cancel()
                await asyncio.gather(send_task, recv_task, deadline_task, return_exceptions=True)

    async def _send_loop(self, session) -> None:
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:
                return
            await session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )

    async def _recv_loop(self, session) -> None:
        async for response in session.receive():
            update = response.session_resumption_update
            if update and update.resumable and update.new_handle:
                self._resumption_handle = update.new_handle

            content = response.server_content
            if content and content.input_transcription and content.input_transcription.text:
                await self._on_text(content.input_transcription.text)
