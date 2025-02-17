# Copyright (c) Microsoft. All rights reserved.

from pydantic import BaseModel, Field

from assistant.assistant_api import AssistantAPI, MessageType
from assistant.modes.markdown_edit import MarkdownEdit, MarkdownEditConfig
from assistant.modes.response import Response
from assistant.modes.router import MODE_DOC_EDIT_TOOL_NAME, Mode, Router
from assistant.types import AssistantMessage, Function, RoutineContext, ToolCall, ToolMessage


class RoutineDefinition(BaseModel):
    file_name: str = Field(default="document.md")
    subdirectory: str = Field(default="documents")


class RoutineState(BaseModel):
    prompt_token_count: int = Field(default=0)


class RoutineIteration:
    def __init__(self, assistant_api: AssistantAPI) -> None:
        self.state = RoutineState()
        self.assistant_api = assistant_api

        # Init modes
        self.router = Router(assistant_api)
        self.response = Response(assistant_api)
        self.doc_edit_skill = MarkdownEdit(
            skill_config=MarkdownEditConfig(),
            assistant_api=self.assistant_api,
        )

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

        # Route to the appropriate mode
        routing_result = await self.router.run(routine_context)

        # Execute the mode
        match routing_result.mode:
            case Mode.DOC_EDIT:
                # Give a notice that we are routing to a mode
                await self.assistant_api.send_message(
                    f"Routing to {routing_result.mode.value} mode",
                    message_type=MessageType.notice,
                )
                doc_edit_output = await self.doc_edit_skill.run(routine_context)
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
            case _:
                pass

        # Last step is always to generate a chat response.
        await self.assistant_api.send_message(
            f"Routing to {Mode.RESPONSE.value} mode",
            message_type=MessageType.notice,
        )
        response_output = await self.response.run(routine_context)
        await self.assistant_api.send_message(response_output.message)
