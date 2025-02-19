# Copyright (c) Microsoft. All rights reserved.

from enum import Enum

import pendulum
from pydantic import BaseModel

from assistant.assistant_api import AssistantAPI
from assistant.helpers import compile_messages
from assistant.prompts.router import (
    MODE_DOC_EDIT_TOOL,
    MODE_DOC_EDIT_TOOL_NAME,
    MODE_RESPONSE_TOOL,
    MODE_RESPONSE_TOOL_NAME,
    ROUTING_MESSAGES,
)
from assistant.types import RoutineContext


class Mode(Enum):
    RESPONSE = MODE_RESPONSE_TOOL_NAME
    DOC_EDIT = MODE_DOC_EDIT_TOOL_NAME


class RouterOutput(BaseModel):
    mode: Mode


class Router:
    def __init__(self, assistant_api: AssistantAPI) -> None:
        self.assistant_api = assistant_api

    async def run(self, routine_context: RoutineContext) -> RouterOutput:
        routing_messages = compile_messages(
            messages=ROUTING_MESSAGES,
            variables={
                "knowledge_cutoff": "2023-10",
                "current_date": pendulum.now().format("YYYY-MM-DD"),
                "attachments": routine_context.attachments,
                "doc": routine_context.current_document,
            },
        )
        routing_messages = routing_messages + routine_context.chat_history
        kwargs = {
            "model": self.assistant_api.get_model_name("gpt-4o"),
            "messages": routing_messages,
            "temperature": 0,
            "tools": [MODE_DOC_EDIT_TOOL, MODE_RESPONSE_TOOL],
            "parallel_tool_calls": False,
            "tool_choice": "required",
        }
        routing_result = await self.assistant_api.chat_completion(**kwargs)  # type: ignore

        # Look at the first tool call and return that
        choice = routing_result.choices[0]
        routing_tool_name = MODE_RESPONSE_TOOL_NAME
        if choice.message.tool_calls:
            function = choice.message.tool_calls[0].function
            if function.name == MODE_DOC_EDIT_TOOL_NAME:
                routing_tool_name = MODE_DOC_EDIT_TOOL_NAME
        else:
            routing_tool_name = MODE_RESPONSE_TOOL_NAME

        return RouterOutput(mode=Mode(routing_tool_name))
