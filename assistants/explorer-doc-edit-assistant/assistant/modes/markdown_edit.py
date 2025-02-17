# Copyright (c) Microsoft. All rights reserved.

import pendulum

from assistant.assistant_api import AssistantAPI
from assistant.helpers import compile_messages
from assistant.prompts.markdown_edit import MD_EDIT_CHANGES_MESSAGES, MD_EDIT_MESSAGES
from assistant.types import MarkdownEditConfig, MarkdownEditOutput, RoutineContext


class MarkdownEdit:
    def __init__(
        self,
        skill_config: MarkdownEditConfig,
        assistant_api: AssistantAPI,
    ) -> None:
        self.skill_config = skill_config
        self.assistant_api = assistant_api

    async def run(self, routine_context: RoutineContext) -> MarkdownEditOutput:
        chat_history_str = "\n".join([f"{message.content}" for message in routine_context.chat_history])

        edit_messages = compile_messages(
            messages=MD_EDIT_MESSAGES,
            variables={
                "knowledge_cutoff": self.skill_config.knowledge_cutoff,
                "current_date": pendulum.now().format("YYYY-MM-DD"),
                "task": self.skill_config.task,
                "context": routine_context.attachments,
                "document": routine_context.current_document,
                "chat_history": chat_history_str,
            },
        )

        kwargs = {
            "messages": edit_messages,
            "model": self.skill_config.name_model,
            "temperature": 0.3,
            "max_completion_tokens": 4000,
        }

        edit_response = await self.assistant_api.chat_completion(**kwargs)
        updated_doc_markdown = edit_response.choices[0].message.content

        if routine_context.current_document != updated_doc_markdown:
            change_summary_messages = compile_messages(
                messages=MD_EDIT_CHANGES_MESSAGES,
                variables={"before_doc": routine_context.current_document, "after_doc": updated_doc_markdown},
            )
            change_summary_kwargs = {
                "messages": change_summary_messages,
                "model": self.skill_config.name_model,
                "temperature": 0.3,
                "max_completion_tokens": 1000,
            }
            change_summary_response = await self.assistant_api.chat_completion(**change_summary_kwargs)
            change_summary = (
                self.skill_config.change_summary_prefix + change_summary_response.choices[0].message.content
            )
        else:
            change_summary = ""

        return MarkdownEditOutput(
            updated_doc_markdown=updated_doc_markdown,
            change_summary=change_summary,
            output_message="",
        )
