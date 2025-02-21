# Copyright (c) Microsoft. All rights reserved.

from pydantic import BaseModel, Field

from assistant.assistant_api import AssistantAPI, MessageType
from assistant.modes.markdown_edit.markdown_edit import MarkdownEdit, MarkdownEditConfig
from assistant.modes.response import Response
from assistant.modes.router import MODE_DOC_EDIT_TOOL_NAME, Mode, Router
from assistant.types import (
    AssistantMessage,
    Function,
    ResponseConfig,
    RoutineContext,
    ToolCall,
    ToolMessage,
)


class RoutineDefinition(BaseModel):
    file_name: str = Field(default="document.md")
    subdirectory: str = Field(default="documents")
    context_token_limit: int = Field(
        default=92000,
        description="This should provide enough of a buffer for the current model limits and context that might be added during the routine.",
    )


class RoutineIteration:
    def __init__(self, assistant_api: AssistantAPI) -> None:
        self.assistant_api = assistant_api

        # Init modes
        self.router = Router(assistant_api)
        self.response = Response(assistant_api)
        self.doc_edit_skill = MarkdownEdit(assistant_api=self.assistant_api)

    async def run_routine(self, definition: RoutineDefinition) -> None:
        # Get and format context. This can be updated over the course of the routine's execution.
        current_doc = self.assistant_api.read_file(definition.file_name, definition.subdirectory)
        chat_history = await self.assistant_api.get_chat_history()
        attachments = await self.assistant_api.get_attachments()
        routine_context = RoutineContext(
            current_document=current_doc,
            chat_history=chat_history,
            attachments=attachments,
        )

        # Check for token limits and stop if exceeded.
        curr_context_tokens = self.get_routine_context_tokens(routine_context)
        if curr_context_tokens > definition.context_token_limit:
            await self.assistant_api.send_message(
                f"The length of the current context at {curr_context_tokens} exceeds the currently supported limit of {definition.context_token_limit}. Please delete messages or attachments to continue.",
                message_type=MessageType.notice,
                debug_info=routine_context.debug_info,
            )
            return

        # Route to the appropriate mode
        routing_result = await self.router.run(routine_context)

        # Initialize ResponseConfig for later
        response_config = ResponseConfig()

        # Execute the mode
        match routing_result.mode:
            case Mode.DOC_EDIT:
                await self.assistant_api.send_message(
                    f"Routing to {routing_result.mode.value} mode",
                    message_type=MessageType.notice,
                )
                doc_edit_output = await self.doc_edit_skill.run(routine_context, config=MarkdownEditConfig())
                self.assistant_api.write_file(
                    doc_edit_output.updated_doc_markdown, definition.file_name, definition.subdirectory
                )
                routine_context.current_document = doc_edit_output.updated_doc_markdown
                await self.assistant_api.send_message(
                    "Document was updated and will be shown in the UX after the routine finishes. Refresh the inspector if changes are not visible.",
                    message_type=MessageType.notice,
                )
                # Add an assistant and tool message to the chat history to give response generation that the page
                # has been updated or a message was sent by the tool.
                internal_assistant_message = doc_edit_output.change_summary or doc_edit_output.output_message
                internal_assistant_message += "\nNow I will generate a chat message to the user."
                chat_history.append(
                    AssistantMessage(
                        content="",
                        tool_calls=[
                            ToolCall(
                                id="call_123",
                                function=Function(name=MODE_DOC_EDIT_TOOL_NAME, arguments={}),
                            )
                        ],
                    )
                )
                chat_history.append(
                    ToolMessage(
                        name="call_123",
                        content=doc_edit_output.change_summary or doc_edit_output.output_message,
                    )
                )
                routine_context.chat_history = chat_history
                # If doc edit mode was triggered, we will use gpt-4o instead because o3 does not work well with the tool messages.
                response_config.use_gpt_4o = True
            case _:
                response_config.use_gpt_4o = False

        # Last step is always to generate a chat response.
        await self.assistant_api.send_message(
            f"Routing to {Mode.RESPONSE.value} mode",
            message_type=MessageType.notice,
        )
        response_output = await self.response.run(routine_context, response_config)
        await self.assistant_api.send_message(response_output.message, debug_info=routine_context.debug_info)

    def get_routine_context_tokens(self, routine_context: RoutineContext) -> int:
        """
        Get the number of tokens in the current routine context.
        Also modifies routine_context.debug_info in-place with the token counts.
        """
        tokens_attachments_total = self.assistant_api.get_tokenizer().num_tokens_in_str(routine_context.attachments)
        tokens_chat_history_total = self.assistant_api.get_tokenizer().num_tokens_in_messages(
            routine_context.chat_history
        )
        tokens_current_document_total = self.assistant_api.get_tokenizer().num_tokens_in_str(
            routine_context.current_document
        )
        total_context_tokens = tokens_attachments_total + tokens_chat_history_total + tokens_current_document_total

        routine_context.debug_info.tokens_attachments_total = tokens_attachments_total
        routine_context.debug_info.tokens_chat_history_total = tokens_chat_history_total
        routine_context.debug_info.tokens_current_document_total = tokens_current_document_total
        routine_context.debug_info.tokens_total = total_context_tokens

        return total_context_tokens
