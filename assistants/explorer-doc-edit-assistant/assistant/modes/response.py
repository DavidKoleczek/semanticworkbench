# Copyright (c) Microsoft. All rights reserved.
import re

import pendulum
from pydantic import BaseModel

from assistant.assistant_api import AssistantAPI
from assistant.helpers import compile_messages
from assistant.prompts.response import RESPONSE_DEV_PROMPT, RESPONSE_USER_ATTACHMENTS_PROMPT, RESPONSE_USER_DOC_PROMPT
from assistant.types import ResponseConfig, RoutineContext, SystemMessage


class ResponseOutput(BaseModel):
    message: str


class Response:
    def __init__(self, assistant_api: AssistantAPI) -> None:
        self.assistant_api = assistant_api

    async def run(self, routine_context: RoutineContext, config: ResponseConfig) -> ResponseOutput:
        if config.use_gpt_4o:
            dev_message = SystemMessage(content=RESPONSE_DEV_PROMPT.content)
        else:
            dev_message = RESPONSE_DEV_PROMPT
        response_messages = compile_messages(
            messages=[dev_message, RESPONSE_USER_ATTACHMENTS_PROMPT, RESPONSE_USER_DOC_PROMPT],
            variables={
                "knowledge_cutoff": "2023-10",
                "current_date": pendulum.now().format("YYYY-MM-DD"),
                "attachments": routine_context.attachments,
                "doc": routine_context.current_document,
            },
        )
        response_messages = response_messages + routine_context.chat_history

        if config.use_gpt_4o:
            kwargs = {
                "messages": response_messages,
                "model": self.assistant_api.get_model_name("gpt-4o"),
                "temperature": 0.7,
                "max_completion_tokens": 8000,
            }
        else:
            kwargs = {
                "messages": response_messages,
                "model": self.assistant_api.get_model_name("o3"),
                "reasoning_effort": "high",
                "max_completion_tokens": 25000,
            }
        response_result = await self.assistant_api.chat_completion(**kwargs)  # type: ignore
        chat_message = response_result.choices[0].message.content
        chat_message = re.sub(r"^\[.*?\]", "", chat_message).lstrip()
        return ResponseOutput(message=chat_message)
