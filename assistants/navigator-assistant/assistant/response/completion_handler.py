import json
import logging
import re
import time
from typing import List

import deepmerge
from assistant_extensions.mcp import (
    ExtendedCallToolRequestParams,
    MCPSession,
    OpenAISamplingHandler,
    handle_mcp_tool_call,
)
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionToolMessageParam,
    ParsedChatCompletion,
)
from openai_client import OpenAIRequestConfig, num_tokens_from_messages
from pydantic import ValidationError
from semantic_workbench_api_model.workbench_model import (
    MessageType,
    NewConversationMessage,
)
from semantic_workbench_assistant.assistant_app import ConversationContext

from .local_tool import LocalTool
from .models import StepResult
from .utils import (
    extract_content_from_mcp_tool_calls,
    get_response_duration_message,
    get_token_usage_message,
)

logger = logging.getLogger(__name__)


async def handle_completion(
    sampling_handler: OpenAISamplingHandler,
    step_result: StepResult,
    completion: ParsedChatCompletion | ChatCompletion,
    mcp_sessions: List[MCPSession],
    context: ConversationContext,
    request_config: OpenAIRequestConfig,
    silence_token: str,
    metadata_key: str,
    response_start_time: float,
    local_tools: list[LocalTool],
) -> StepResult:
    # get service and request configuration for generative model
    request_config = request_config

    # get the total tokens used for the completion
    total_tokens = completion.usage.total_tokens if completion.usage else 0

    content: str | None = None

    if (completion.choices[0].message.content is not None) and (completion.choices[0].message.content.strip() != ""):
        content = completion.choices[0].message.content

    # check if the completion has tool calls
    tool_calls: list[ExtendedCallToolRequestParams] = []
    if completion.choices[0].message.tool_calls:
        ai_context, tool_calls = extract_content_from_mcp_tool_calls([
            ExtendedCallToolRequestParams(
                id=tool_call.id,
                name=tool_call.function.name,
                arguments=json.loads(
                    tool_call.function.arguments,
                ),
            )
            for tool_call in completion.choices[0].message.tool_calls
        ])
        if content is None:
            if ai_context is not None and ai_context.strip() != "":
                content = ai_context
            # else:
            #     content = f"[Assistant is calling tools: {', '.join([tool_call.name for tool_call in tool_calls])}]"

    if content is None:
        content = ""

    # update the metadata with debug information
    deepmerge.always_merger.merge(
        step_result.metadata,
        {
            "debug": {
                metadata_key: {
                    "response": completion.model_dump(),
                },
            },
        },
    )

    # Add tool calls to the metadata
    deepmerge.always_merger.merge(
        step_result.metadata,
        {
            "tool_calls": [tool_call.model_dump(mode="json") for tool_call in tool_calls],
        },
    )

    # Create the footer items for the response
    footer_items = []

    # Add the token usage message to the footer items
    if total_tokens > 0:
        completion_tokens = completion.usage.completion_tokens if completion.usage else 0
        request_tokens = total_tokens - completion_tokens
        footer_items.append(
            get_token_usage_message(
                max_tokens=request_config.max_tokens,
                total_tokens=total_tokens,
                request_tokens=request_tokens,
                completion_tokens=completion_tokens,
            )
        )

        await context.update_conversation(
            metadata={
                "token_counts": {
                    "total": total_tokens,
                    "max": request_config.max_tokens,
                }
            }
        )

    # Track the end time of the response generation and calculate duration
    response_end_time = time.time()
    response_duration = response_end_time - response_start_time

    # Add the response duration to the footer items
    footer_items.append(get_response_duration_message(response_duration))

    # Update the metadata with the footer items
    deepmerge.always_merger.merge(
        step_result.metadata,
        {
            "footer_items": footer_items,
        },
    )

    # Set the conversation tokens for the turn result
    step_result.conversation_tokens = total_tokens

    # strip out the username from the response
    if content.startswith("["):
        content = re.sub(r"\[.*\]:\s", "", content)

    # Handle silence token
    if content.lstrip().startswith(silence_token):
        # No response from the AI, nothing to send
        pass
    else:
        # Send the AI's response to the conversation
        await context.send_messages(
            NewConversationMessage(
                content=content,
                message_type=MessageType.chat if content else MessageType.log,
                metadata=step_result.metadata,
            )
        )

    # Check for tool calls
    if len(tool_calls) == 0:
        # No tool calls, exit the loop
        step_result.status = "final"
        return step_result

    # Handle tool calls
    tool_call_count = 0
    for tool_call in tool_calls:
        tool_call_count += 1
        tool_call_status = f"using tool `{tool_call.name}`"
        async with context.set_status(f"{tool_call_status}..."):
            try:
                local_tool = next((local_tool for local_tool in local_tools if tool_call.name == local_tool.name), None)
                if local_tool:
                    # If the tool call is a local tool, handle it locally
                    logger.info("executing local tool call; tool name: %s", tool_call.name)
                    try:
                        typed_argument = local_tool.argument_model.model_validate(tool_call.arguments)
                    except ValidationError as e:
                        logger.exception("error validating local tool call arguments")
                        content = f"Error validating local tool call arguments: {e}"
                    else:
                        content = await local_tool.func(typed_argument, context)

                else:
                    tool_call_result = await handle_mcp_tool_call(
                        mcp_sessions,
                        tool_call,
                        f"{metadata_key}:request:tool_call_{tool_call_count}",
                    )

                    # Update content and metadata with tool call result metadata
                    deepmerge.always_merger.merge(step_result.metadata, tool_call_result.metadata)

                    # FIXME only supporting 1 content item and it's text for now, should support other content types/quantity
                    # Get the content from the tool call result
                    content = next(
                        (content_item.text for content_item in tool_call_result.content if content_item.type == "text"),
                        "[tool call returned no content]",
                    )

            except Exception as e:
                logger.exception("error handling tool call '%s'", tool_call.name)
                deepmerge.always_merger.merge(
                    step_result.metadata,
                    {
                        "debug": {
                            f"{metadata_key}:request:tool_call_{tool_call_count}": {
                                "error": str(e),
                            },
                        },
                    },
                )
                content = f"Error executing tool '{tool_call.name}': {e}"

        # Add the token count for the tool call result to the total token count
        step_result.conversation_tokens += num_tokens_from_messages(
            messages=[
                ChatCompletionToolMessageParam(
                    role="tool",
                    content=content,
                    tool_call_id=tool_call.id,
                )
            ],
            model=request_config.model,
        )

        # Add the tool_result payload to metadata
        deepmerge.always_merger.merge(
            step_result.metadata,
            {
                "tool_result": {
                    "content": content,
                    "tool_call_id": tool_call.id,
                },
            },
        )

        await context.send_messages(
            NewConversationMessage(
                content=content,
                message_type=MessageType.log,
                metadata=step_result.metadata,
            )
        )

    return step_result
