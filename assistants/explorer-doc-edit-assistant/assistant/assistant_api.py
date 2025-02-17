# Copyright (c) Microsoft. All rights reserved.

# Provider a common interface for interacting with the Semantic Workbench Assistant Service and the Workbench Service.

import json
import logging
from pathlib import Path
from typing import Any

import pendulum
from assistant_extensions.attachments._attachments import _get_attachments, log_and_send_message_on_error
from openai import AsyncAzureOpenAI
from openai_client.client import _get_azure_bearer_token_provider
from openai_client.config import AzureOpenAIServiceConfig
from semantic_workbench_api_model.workbench_model import (
    MessageType,
    NewConversationMessage,
)
from semantic_workbench_assistant.assistant_app import (
    AssistantConversationInspectorStateDataModel,
    BaseModelAssistantConfig,
    ConversationContext,
    storage_directory_for_context,
)

from assistant.config import AssistantConfigModel
from assistant.types import AssistantMessage, MessageT, UserMessage

logger = logging.getLogger(__name__)


class AssistantAPI:
    def __init__(
        self,
        context: ConversationContext,
        service_config: AzureOpenAIServiceConfig,
    ) -> None:
        self.context = context
        self.service_config = service_config
        self.openai_client = AsyncAzureOpenAI(
            azure_ad_token_provider=_get_azure_bearer_token_provider(),
            azure_endpoint=str(service_config.azure_openai_endpoint),
            api_version="2025-01-01-preview",
        )

    async def send_message(self, message: str, message_type: MessageType = MessageType.chat) -> None:
        """
        Sends a chat message to the UX.
        """
        await self.context.send_messages(
            NewConversationMessage(
                content=message,
                message_type=message_type,
            )
        )

    async def chat_completion(self, **kwargs: dict) -> Any:
        """
        Perform a chat completion request to the OpenAI API. TODO: Make this more robust.
        """
        # Convert messages to the dict format that is expected
        formatted_messages = [message.model_dump(mode="json", exclude_none=True) for message in kwargs["messages"]]
        # If there was a tool_message (role = "tool"), change the "name" parameter to "tool_call_id"
        for message in formatted_messages:
            if message["role"] == "tool":
                message["tool_call_id"] = message.pop("name")

        # For any assistant message with tool calls, the function needs to have arguments converted to a string
        for message in formatted_messages:
            if message["role"] == "assistant" and "tool_calls" in message:
                for tool_call in message["tool_calls"]:
                    tool_call["function"]["arguments"] = json.dumps(tool_call["function"]["arguments"])

        kwargs["messages"] = formatted_messages  # type: ignore
        response = await self.openai_client.chat.completions.create(**kwargs)  # type: ignore
        return response

    async def get_chat_history(self) -> list[MessageT]:
        """
        Get the conversation history messages from the current conversation.
        """
        participants = await self.context.get_participants(include_inactive=True)

        history: list[MessageT] = []
        before_message_id = None
        while True:
            # get the next batch of messages
            messages_response = await self.context.get_messages(limit=100, before=before_message_id)
            messages_list = messages_response.messages

            # if there are no more messages, break the loop
            if not messages_list or messages_list.count == 0:
                break

            # set the before_message_id for the next batch of messages
            before_message_id = messages_list[0].id

            for message in messages_list:
                # add the message to the completion messages, treating any message from a source other than the assistant
                # as a user message
                conversation_participant = next(
                    (
                        participant
                        for participant in participants.participants
                        if participant.id == message.sender.participant_id
                    ),
                    None,
                )
                participant_name = conversation_participant.name if conversation_participant else "unknown"
                message_dt = pendulum.instance(message.timestamp).strftime("%b %-d, %Y at %-I:%M %p")
                message_content = f"[{participant_name}, {message_dt}] {message.content}"
                if message.sender.participant_id == self.context.assistant.id:
                    history.append(AssistantMessage(content=message_content))
                else:
                    history.append(UserMessage(content=message_content))

        return history

    async def get_attachments(self) -> str:
        """
        Get the attachments from the current conversation.
        For now assumes they will fit within the context window and returns them as a pre-formatted string.
        """
        attachments = await _get_attachments(
            self.context,
            error_handler=log_and_send_message_on_error,
            include_filenames=None,
            exclude_filenames=[],
        )
        attachments_string = ""
        for attachment in attachments:
            if not attachment.error and attachment.content:
                attachments_string += f"""<attachment-{attachment.filename}>
{attachment.content.strip()}
</attachment-{attachment.filename}>
"""
        return attachments_string.strip()

    def write_file(self, content: str, filename: str, subdirectory: str) -> None:
        """
        Write content to a file.

        Args:
            content: The content to write
            filename: The filename to write to
            subdirectory: The subdirectory to use
        """
        path = self._get_doc_storage_path(subdirectory, filename)
        if not path.parent.exists():
            path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")

    def read_file(self, filename: str, subdirectory: str) -> str:
        """
        Read content from a file.

        Args:
            filename: The filename to read from
            subdirectory: The subdirectory to use

        Returns:
            The file contents or empty string if file doesn't exist
        """
        path = self._get_doc_storage_path(subdirectory, filename)
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Error reading file {path}: {e}")
                return ""
        return ""

    def _get_doc_storage_path(self, subdirectory: str, filename: str | None = None) -> Path:
        """
        Get the path to the directory for storing files.

        Args:
            subdirectory: The subdirectory name
            filename: Optional filename to append to the path

        Returns:
            Path object for the requested location
        """
        path = storage_directory_for_context(self.context) / subdirectory
        if filename:
            path /= filename
        return path


# Displaying the current document in the inspector
class DocumentInspectorStateProvider:
    display_name = "Current Document"
    description = "Current state of the markdown document that can be edited by the assistant."

    def __init__(
        self,
        config_provider: BaseModelAssistantConfig["AssistantConfigModel"],
    ) -> None:
        self.config_provider = config_provider

    async def get(self, context: ConversationContext) -> AssistantConversationInspectorStateDataModel:
        """
        Get the state for the conversation.
        """

        doc: str = _read_doc_state(context)
        return AssistantConversationInspectorStateDataModel({"content": doc})


def _get_doc_storage_path(context: ConversationContext, filename: str | None = None) -> Path:
    """
    Get the path to the directory for storing guided conversation files.
    """
    path = storage_directory_for_context(context) / "documents"
    if filename:
        path /= filename
    return path


def _read_doc_state(context: ConversationContext) -> str:
    """
    Read the content of the Markdown document from a file.
    Returns empty string if file doesn't exist.
    """
    path = _get_doc_storage_path(context, "document.md")
    if path.exists():
        try:
            return path.read_text()
        except Exception:
            return ""
    return ""
