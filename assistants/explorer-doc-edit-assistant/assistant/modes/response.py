# Copyright (c) Microsoft. All rights reserved.

import pendulum
from pydantic import BaseModel

from assistant.assistant_api import AssistantAPI
from assistant.helpers import compile_messages
from assistant.prompts.response import (
    RESPONSE_MESSAGES,
)
from assistant.types import RoutineContext


class ResponseOutput(BaseModel):
    message: str


class Response:
    def __init__(self, assistant_api: AssistantAPI) -> None:
        self.assistant_api = assistant_api

    async def run(self, routine_context: RoutineContext) -> ResponseOutput:
        response_messages = compile_messages(
            messages=RESPONSE_MESSAGES,
            variables={
                "knowledge_cutoff": "2023-10",
                "current_date": pendulum.now().format("YYYY-MM-DD"),
                "attachments": routine_context.attachments,
                "doc": routine_context.current_document,
            },
        )
        response_messages = response_messages + routine_context.chat_history

        kwargs = {
            "model": "gpt-4o-2024-11-20",
            "messages": response_messages,
            "temperature": 0.7,
        }
        response_result = await self.assistant_api.chat_completion(**kwargs)  # type: ignore
        chat_message = response_result.choices[0].message.content
        return ResponseOutput(message=chat_message)
