# Copyright (c) Microsoft. All rights reserved.

# Doc Edit Assistant
#
# This assistant shows document editing capabilities
#

import logging
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

import deepmerge
import pendulum
from assistant_extensions.ai_clients.model import CompletionMessage
from assistant_extensions.artifacts import ArtifactsExtension
from assistant_extensions.attachments import AttachmentsExtension
from semantic_workbench_api_model.workbench_model import (
    ConversationMessage,
    ConversationParticipant,
    MessageType,
    NewConversationMessage,
)
from semantic_workbench_assistant.assistant_app import (
    AssistantConversationInspectorStateDataModel,
    BaseModelAssistantConfig,
    ConversationContext,
    storage_directory_for_context,
)

from assistant.doc_edit_skill import DocEditSkill, DocEditSkillConfig, DocEditSkillDefinition
from assistant.helpers import compile_messages
from assistant.prompts.response import RESPONSE_MESSAGES
from assistant.prompts.routing import (
    MODE_ANSWER_TOOL,
    MODE_ANSWER_TOOL_NAME,
    MODE_DOC_EDIT_TOOL,
    MODE_DOC_EDIT_TOOL_NAME,
    ROUTING_MESSAGES,
)

from ..config import AssistantConfigModel
from .model import NumberTokensResult, ResponseProvider
from .response_anthropic import AnthropicResponseProvider
from .response_openai import OpenAIResponseProvider

logger = logging.getLogger(__name__)


#
# region Response
#


# demonstrates how to respond to a conversation message using the OpenAI API.
async def respond_to_conversation(
    artifacts_extension: ArtifactsExtension,
    attachments_extension: AttachmentsExtension,
    context: ConversationContext,
    config: AssistantConfigModel,
    metadata: dict[str, Any] = {},
) -> None:
    """
    Respond to a conversation message.

    This method uses the OpenAI API to generate a response to the message.

    It includes any attachments as individual system messages before the chat history, along with references
    to the attachments in the point in the conversation where they were mentioned. This allows the model to
    consider the full contents of the attachments separate from the conversation, but with the context of
    where they were mentioned and any relevant surrounding context such as how to interpret the attachment
    or why it was shared or what to do with it.
    """

    current_document = _read_doc_state(context)

    response_provider = (
        AnthropicResponseProvider(assistant_config=config, anthropic_client_config=config.ai_client_config)
        if config.ai_client_config.ai_service_type == "anthropic"
        else OpenAIResponseProvider(
            artifacts_extension=artifacts_extension,
            conversation_context=context,
            assistant_config=config,
            openai_client_config=config.ai_client_config,
        )
    )

    request_config = config.ai_client_config.request_config

    # define the metadata key for any metadata created within this method
    method_metadata_key = "respond_to_conversation"

    # track the start time of the response generation
    response_start_time = time.time()

    # get the list of conversation participants
    participants_response = await context.get_participants(include_inactive=True)

    # establish a token to be used by the AI model to indicate no response
    silence_token = "{{SILENCE}}"

    system_message_content = f'{config.instruction_prompt}\n\nYour name is "{context.assistant.name}".'
    if len(participants_response.participants) > 2:
        system_message_content += (
            "\n\n"
            f"There are {len(participants_response.participants)} participants in the conversation,"
            " including you as the assistant and the following users:"
            + ",".join([
                f' "{participant.name}"'
                for participant in participants_response.participants
                if participant.id != context.assistant.id
            ])
            + "\n\nYou do not need to respond to every message. Do not respond if the last thing said was a closing"
            " statement such as 'bye' or 'goodbye', or just a general acknowledgement like 'ok' or 'thanks'. Do not"
            f' respond as another user in the conversation, only as "{context.assistant.name}".'
            " Sometimes the other users need to talk amongst themselves and that is ok. If the conversation seems to"
            f' be directed at you or the general audience, go ahead and respond.\n\nSay "{silence_token}" to skip'
            " your turn."
        )

    # add the artifact agent instruction prompt to the system message content
    if config.extensions_config.artifacts.enabled:
        system_message_content += f"\n\n{config.extensions_config.artifacts.instruction_prompt}"

    # add the guardrails prompt to the system message content
    system_message_content += f"\n\n{config.guardrails_prompt}"

    # initialize the completion messages with the system message
    completion_messages: list[CompletionMessage] = [
        CompletionMessage(
            role="system",
            content=system_message_content,
        )
    ]

    token_count = 0

    # calculate the token count for the messages so far
    result = await _num_tokens_from_messages(
        context=context,
        response_provider=response_provider,
        messages=completion_messages,
        model=request_config.model,
        metadata=metadata,
        metadata_key="system_message",
    )
    if result is not None:
        token_count += result.count
    else:
        return

    # generate the attachment messages from the attachment agent
    attachment_messages = await attachments_extension.get_completion_messages_for_attachments(
        context,
        config=config.extensions_config.attachments,
    )
    result = await _num_tokens_from_messages(
        context=context,
        response_provider=response_provider,
        messages=attachment_messages,
        model=request_config.model,
        metadata=metadata,
        metadata_key="attachment_messages",
    )
    if result is not None:
        token_count += result.count
    else:
        return

    # calculate the total available tokens for the response generation
    available_tokens = request_config.max_tokens - request_config.response_tokens

    history_messages = await _get_history_messages(
        response_provider=response_provider,
        context=context,
        participants=participants_response.participants,
        converter=_conversation_message_to_completion_messages,
        model=request_config.model,
        token_limit=available_tokens - token_count,
    )

    # add the attachment messages to the completion messages, either inline or as separate messages
    if config.use_inline_attachments:
        # inject the attachment messages inline into the history messages
        history_messages = _inject_attachments_inline(history_messages, attachment_messages)
    else:
        # add the attachment messages to the completion messages before the history messages
        completion_messages.extend(attachment_messages)

    # add the history messages to the completion messages
    completion_messages.extend(history_messages)

    result = await _num_tokens_from_messages(
        context=context,
        response_provider=response_provider,
        messages=completion_messages,
        model=request_config.model,
        metadata=metadata,
        metadata_key=method_metadata_key,
    )
    if result is not None:
        estimated_token_count = result.count
        if estimated_token_count > request_config.max_tokens:
            await context.send_messages(
                NewConversationMessage(
                    content=(
                        f"You've exceeded the token limit of {request_config.max_tokens} in this conversation ({estimated_token_count})."
                        " This assistant does not support recovery from this state."
                        " Please start a new conversation and let us know you ran into this."
                    ),
                    message_type=MessageType.chat,
                )
            )
            return
    else:
        return

    # set default response message type
    message_type = MessageType.chat

    completion_messages_openai: list[dict[str, str]] = []
    for message in completion_messages[1:]:  # TODO: For now remove the first message which is hardcoded.
        completion_messages_openai.append({
            "role": message.role,
            "content": message.content,
        })

    # Step 1. Route to the appropriate mode
    routing_messages = compile_messages(
        messages=ROUTING_MESSAGES,
        variables={
            "knowledge_cutoff": "2023-10",
            "current_date": pendulum.now().format("YYYY-MM-DD"),
            "attachments": "",
            "doc": current_document,
        },
    )
    routing_messages.extend(completion_messages_openai)
    kwargs = {
        "model": "gpt-4o-2024-11-20",
        "messages": routing_messages,
        "temperature": 0.1,
        "tools": [MODE_DOC_EDIT_TOOL, MODE_ANSWER_TOOL],
        "parallel_tool_calls": False,
    }
    routing_result = await response_provider.chat_completion(**kwargs)  # type: ignore
    choice = routing_result.choices[0]
    routing_tool_name = MODE_ANSWER_TOOL_NAME
    if choice.message.tool_calls:
        function = choice.message.tool_calls[0].function
        if function.name == MODE_DOC_EDIT_TOOL_NAME:
            routing_tool_name = MODE_DOC_EDIT_TOOL_NAME

    # Step 2. Execute the mode (if mode is response, skip to 3)
    if routing_tool_name == MODE_ANSWER_TOOL_NAME:
        pass
    elif routing_tool_name == MODE_DOC_EDIT_TOOL_NAME:
        doc_edit_skill = DocEditSkill(
            definition=DocEditSkillDefinition(
                context="",  # TODO: Add back attachments
                doc_markdown=current_document,
                conversation_history=completion_messages_openai,
            ),
            skill_config=DocEditSkillConfig(),
            response_provider=response_provider,
        )
        doc_edit_output = await doc_edit_skill.run()
        # Append chat result as a new message and update current document.
        completion_messages_openai.append({
            "role": "assistant",
            "content": doc_edit_output.change_summary or doc_edit_output.output_message,
        })
        _write_doc_state(context, doc_edit_output.updated_doc_markdown)
        current_document = _read_doc_state(context)

    # Step 3. Last step is always to generate a chat response.
    response_messages = compile_messages(
        messages=RESPONSE_MESSAGES,
        variables={
            "knowledge_cutoff": "2023-10",
            "current_date": pendulum.now().format("YYYY-MM-DD"),
            "attachments": "",  # TODO: Format attachments
            "doc": current_document,
        },
    )
    response_messages.extend(completion_messages_openai)

    kwargs = {
        "model": "gpt-4o-2024-11-20",
        "messages": response_messages,
        "temperature": 0.7,
    }
    response_result = await response_provider.chat_completion(**kwargs)  # type: ignore
    chat_message = response_result.choices[0].message.content

    # TODO: Handle either tool call or response here.

    # TODO: BELOW THIS IS UNTESTED
    content = chat_message
    message_type = MessageType.chat
    completion_total_tokens = 1

    # create the footer items for the response
    footer_items = []

    # add the token usage message to the footer items
    if completion_total_tokens > 0:
        footer_items.append(_get_token_usage_message(request_config.max_tokens, completion_total_tokens))

    # track the end time of the response generation
    response_end_time = time.time()
    response_duration = response_end_time - response_start_time

    # add the response duration to the footer items
    footer_items.append(_get_response_duration_message(response_duration))

    # update the metadata with the footer items
    deepmerge.always_merger.merge(
        metadata,
        {
            "footer_items": footer_items,
        },
    )

    if content:
        # strip out the username from the response
        if content.startswith("["):
            content = re.sub(r"\[.*\]:\s", "", content)

        # model sometimes puts extra spaces in the response, so remove them
        # when checking for the silence token
        if content.replace(" ", "") == silence_token:
            # if debug output is enabled, notify the conversation that the assistant chose to remain silent
            if config.enable_debug_output:
                # add debug metadata to indicate the assistant chose to remain silent
                deepmerge.always_merger.merge(
                    metadata,
                    {
                        "debug": {
                            method_metadata_key: {
                                "silence_token": True,
                            },
                        },
                        "attribution": "debug output",
                        "generated_content": False,
                    },
                )
                # send a notice message to the conversation
                await context.send_messages(
                    NewConversationMessage(
                        message_type=MessageType.notice,
                        content="[assistant chose to remain silent]",
                        metadata=metadata,
                    )
                )
            return

        # override message type if content starts with /
        if content.startswith("/"):
            message_type = MessageType.command_response

    # send the response to the conversation
    await context.send_messages(
        NewConversationMessage(
            content=content or "[no response from openai]",
            message_type=message_type,
            metadata=metadata,
        )
    )

    # check the token usage and send a warning if it is high
    if completion_total_tokens and config.high_token_usage_warning.enabled:
        # calculate the token count for the warning threshold
        token_count_for_warning = request_config.max_tokens * (config.high_token_usage_warning.threshold / 100)

        # check if the completion total tokens exceed the warning threshold
        if completion_total_tokens > token_count_for_warning:
            content = f"{config.high_token_usage_warning.message}\n\nTotal tokens used: {completion_total_tokens}"

            # send a notice message to the conversation that the token usage is high
            await context.send_messages(
                NewConversationMessage(
                    content=content,
                    message_type=MessageType.notice,
                    metadata={
                        "debug": {
                            "high_token_usage_warning": {
                                "completion_total_tokens": completion_total_tokens,
                                "threshold": config.high_token_usage_warning.threshold,
                                "token_count_for_warning": token_count_for_warning,
                            }
                        },
                        "attribution": "system",
                    },
                )
            )


# endregion

#
# region Inspector
#


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


# endregion

#
# region Helpers
#

# TODO: move to a common module, such as either the openai_client or attachment module for easy re-use in other assistants


def _get_doc_storage_path(context: ConversationContext, filename: str | None = None) -> Path:
    """
    Get the path to the directory for storing guided conversation files.
    """
    path = storage_directory_for_context(context) / "documents"
    if filename:
        path /= filename
    return path


def _write_doc_state(context: ConversationContext, content: str) -> None:
    """
    Write the Markdown content to a file.
    """
    path = _get_doc_storage_path(context)
    if not path.exists():
        path.mkdir(parents=True)
    path = path / "document.md"
    path.write_text(content)


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


async def _num_tokens_from_messages(
    context: ConversationContext,
    response_provider: ResponseProvider,
    messages: Sequence[CompletionMessage],
    model: str,
    metadata: dict[str, Any],
    metadata_key: str,
) -> NumberTokensResult | None:
    """
    Calculate the number of tokens required to generate the completion messages.
    """
    try:
        return await response_provider.num_tokens_from_messages(
            messages=messages, model=model, metadata_key=metadata_key
        )
    except Exception as e:
        logger.exception(f"exception occurred calculating token count: {e}")
        deepmerge.always_merger.merge(
            metadata,
            {
                "debug": {
                    metadata_key: {
                        "num_tokens_from_messages": {
                            "request": {
                                "messages": messages,
                                "model": model,
                            },
                            "error": str(e),
                        },
                    },
                }
            },
        )
        await context.send_messages(
            NewConversationMessage(
                content="An error occurred while calculating the token count for the messages.",
                message_type=MessageType.notice,
                metadata=metadata,
            )
        )


async def _conversation_message_to_completion_messages(
    context: ConversationContext, message: ConversationMessage, participants: list[ConversationParticipant]
) -> list[CompletionMessage]:
    """
    Convert a conversation message to a list of completion messages.
    """

    # some messages may have multiple parts, such as a text message with an attachment
    completion_messages: list[CompletionMessage] = []

    # add the message to the completion messages, treating any message from a source other than the assistant
    # as a user message
    if message.sender.participant_id == context.assistant.id:
        completion_messages.append(CompletionMessage(role="assistant", content=_format_message(message, participants)))

    else:
        # add the user message to the completion messages
        completion_messages.append(CompletionMessage(role="user", content=_format_message(message, participants)))

        if message.filenames and len(message.filenames) > 0:
            # add a system message to indicate the attachments
            completion_messages.append(
                CompletionMessage(role="system", content=f"Attachment(s): {', '.join(message.filenames)}")
            )

    return completion_messages


async def _get_history_messages(
    response_provider: ResponseProvider,
    context: ConversationContext,
    participants: list[ConversationParticipant],
    converter: Callable[
        [ConversationContext, ConversationMessage, list[ConversationParticipant]],
        Awaitable[list[CompletionMessage]],
    ],
    model: str,
    token_limit: int | None = None,
) -> list[CompletionMessage]:
    """
    Get all messages in the conversation, formatted for use in a completion.
    """

    # each call to get_messages will return a maximum of 100 messages
    # so we need to loop until all messages are retrieved
    # if token_limit is provided, we will stop when the token limit is reached

    history = []
    token_count = 0
    before_message_id = None

    while True:
        # get the next batch of messages
        messages_response = await context.get_messages(limit=100, before=before_message_id)
        messages_list = messages_response.messages

        # if there are no more messages, break the loop
        if not messages_list or messages_list.count == 0:
            break

        # set the before_message_id for the next batch of messages
        before_message_id = messages_list[0].id

        # messages are returned in reverse order, so we need to reverse them
        for message in reversed(messages_list):
            # format the message
            formatted_message_list = await converter(context, message, participants)
            try:
                results = await _num_tokens_from_messages(
                    context=context,
                    response_provider=response_provider,
                    messages=formatted_message_list,
                    model=model,
                    metadata={},
                    metadata_key="get_history_messages",
                )
                if results is not None:
                    token_count += results.count
            except Exception as e:
                logger.exception(f"exception occurred calculating token count: {e}")

            # if a token limit is provided and the token count exceeds the limit, break the loop
            if token_limit and token_count > token_limit:
                break

            # insert the formatted messages into the beginning of the history list
            history = formatted_message_list + history

    # return the formatted messages
    return history


def _inject_attachments_inline(
    history_messages: list[CompletionMessage],
    attachment_messages: Sequence[CompletionMessage],
) -> list[CompletionMessage]:
    """
    Inject the attachment messages inline into the history messages.
    """

    # iterate over the history messages and for every message that contains an attachment,
    # find the related attachment message and replace the attachment message with the inline attachment content
    for index, history_message in enumerate(history_messages):
        # if the history message does not contain content, as a string value, skip
        content = history_message.content
        if not content or not isinstance(content, str):
            # TODO: handle list content, which may contain multiple parts including images
            continue

        # get the attachment filenames string from the history message content
        attachment_filenames_string = re.findall(r"Attachment\(s\): (.+)", content)

        # if the history message does not contain an attachment filenames string, skip
        if not attachment_filenames_string:
            continue

        # split the attachment filenames string into a list of attachment filenames
        attachment_filenames = [filename.strip() for filename in attachment_filenames_string[0].split(",")]

        # initialize a list to store the replacement messages
        replacement_messages = []

        # iterate over the attachment filenames and find the related attachment message
        for attachment_filename in attachment_filenames:
            # find the related attachment message
            attachment_message = next(
                (
                    attachment_message
                    for attachment_message in attachment_messages
                    if f"<ATTACHMENT><FILENAME>{attachment_filename}</FILENAME>" in str(attachment_message.content)
                ),
                None,
            )

            if attachment_message:
                # replace the attachment message with the inline attachment content
                replacement_messages.append(attachment_message)

        # if there are replacement messages, replace the history message with the replacement messages
        if len(replacement_messages) > 0:
            history_messages[index : index + 1] = replacement_messages

    return history_messages


def _get_response_duration_message(response_duration: float) -> str:
    """
    Generate a display friendly message for the response duration, to be added to the footer items.
    """

    return f"Response time: {response_duration:.2f} seconds"


def _get_token_usage_message(
    max_tokens: int,
    completion_total_tokens: int,
) -> str:
    """
    Generate a display friendly message for the token usage, to be added to the footer items.
    """

    def get_display_count(tokens: int) -> str:
        # if less than 1k, return the number of tokens
        # if greater than or equal to 1k, return the number of tokens in k
        # use 1 decimal place for k
        # drop the decimal place if the number of tokens in k is a whole number
        if tokens < 1000:
            return str(tokens)
        else:
            tokens_in_k = tokens / 1000
            if tokens_in_k.is_integer():
                return f"{int(tokens_in_k)}k"
            else:
                return f"{tokens_in_k:.1f}k"

    return f"Tokens used: {get_display_count(completion_total_tokens)} of {get_display_count(max_tokens)} ({int(completion_total_tokens / max_tokens * 100)}%)"


def _format_message(message: ConversationMessage, participants: list[ConversationParticipant]) -> str:
    """
    Format a conversation message for display.
    """
    conversation_participant = next(
        (participant for participant in participants if participant.id == message.sender.participant_id),
        None,
    )
    participant_name = conversation_participant.name if conversation_participant else "unknown"
    message_datetime = message.timestamp.strftime("%Y-%m-%d %H:%M:%S")
    return f"[{participant_name} - {message_datetime}]: {message.content}"


# endregion
