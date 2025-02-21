# Copyright (c) Microsoft. All rights reserved.

import json

import pendulum

from assistant.assistant_api import AssistantAPI
from assistant.helpers import compile_messages
from assistant.modes.markdown_edit.utils import blockify, construct_page_for_llm, execute_tools, unblockify
from assistant.prompts.markdown_edit import (
    MD_EDIT_CHANGES_MESSAGES,
    MD_EDIT_CONVERT_MESSAGES,
    MD_EDIT_REASONING_MESSAGES,
    MD_EDIT_TOOL_DEF,
    MD_EDIT_TOOL_NAME,
    SEND_MESSAGE_TOOL_DEF,
    SEND_MESSAGE_TOOL_NAME,
)
from assistant.types import MarkdownEditConfig, MarkdownEditOutput, RoutineContext


class MarkdownEdit:
    def __init__(
        self,
        assistant_api: AssistantAPI,
    ) -> None:
        self.assistant_api = assistant_api

    async def run(self, routine_context: RoutineContext, config: MarkdownEditConfig) -> MarkdownEditOutput:
        blockified_page = blockify(routine_context.current_document)
        page_for_llm = construct_page_for_llm(blockified_page)

        chat_history_str = "\n".join([f"{message.content}" for message in routine_context.chat_history])

        reasoning_messages = compile_messages(
            messages=MD_EDIT_REASONING_MESSAGES,
            variables={
                "knowledge_cutoff": config.knowledge_cutoff,
                "current_date": pendulum.now().format("YYYY-MM-DD"),
                "task": config.task,
                "context": routine_context.attachments,
                "document": page_for_llm,
                "chat_history": chat_history_str,
            },
        )

        kwargs = {
            "messages": reasoning_messages,
            "model": self.assistant_api.get_model_name("o3"),
            "reasoning_effort": "high",
            "max_completion_tokens": 20000,
        }

        reasoning_response = await self.assistant_api.chat_completion(**kwargs)
        reasoning = reasoning_response.choices[0].message.content

        convert_messages = compile_messages(
            messages=MD_EDIT_CONVERT_MESSAGES,
            variables={"reasoning": reasoning},
        )
        convert_kwargs = {
            "messages": convert_messages,
            "model": self.assistant_api.get_model_name("gpt-4o"),
            "temperature": 0,
            "max_completion_tokens": 4000,
            "tools": [MD_EDIT_TOOL_DEF, SEND_MESSAGE_TOOL_DEF],
            "tool_choice": "required",
            "parallel_tool_calls": False,
        }

        convert_response = await self.assistant_api.chat_completion(**convert_kwargs)

        updated_doc_markdown = routine_context.current_document
        change_summary = ""
        output_message = ""

        if convert_response.choices[0].message.tool_calls:
            tool_call = convert_response.choices[0].message.tool_calls[0].function
            # If the the model called the send_message, don't update the doc and return the message
            if tool_call.name == SEND_MESSAGE_TOOL_NAME:
                output_message = convert_response.choices[0].message.content
            elif tool_call.name == MD_EDIT_TOOL_NAME:
                tool_call.arguments = json.loads(tool_call.arguments)
                blocks = blockify(updated_doc_markdown)
                blocks = execute_tools(blocks=blocks, edit_tool_call=tool_call)  # type: ignore
                updated_doc_markdown = unblockify(blocks)
                if updated_doc_markdown != routine_context.current_document:
                    change_summary = await self._change_summary(
                        routine_context=routine_context,
                        updated_doc_markdown=updated_doc_markdown,
                        config=config,
                    )
                else:
                    change_summary = "No changes were made to the document."
        else:
            output_message = "Something went wrong when editing the document and no changes were made."

        return MarkdownEditOutput(
            updated_doc_markdown=updated_doc_markdown,
            change_summary=change_summary,
            output_message=output_message,
        )

    async def _change_summary(
        self, routine_context: RoutineContext, updated_doc_markdown: str, config: MarkdownEditConfig
    ) -> str:
        change_summary_messages = compile_messages(
            messages=MD_EDIT_CHANGES_MESSAGES,
            variables={
                "before_doc": routine_context.current_document,
                "after_doc": updated_doc_markdown,
            },
        )
        change_summary_kwargs = {
            "messages": change_summary_messages,
            "model": self.assistant_api.get_model_name("gpt-4o"),
            "temperature": 0.3,
            "max_completion_tokens": 1000,
        }
        change_summary_response = await self.assistant_api.chat_completion(**change_summary_kwargs)
        change_summary = config.change_summary_prefix + change_summary_response.choices[0].message.content
        return change_summary
