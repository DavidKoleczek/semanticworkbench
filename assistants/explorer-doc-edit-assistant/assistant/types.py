# Copyright (c) Microsoft. All rights reserved.

from enum import Enum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

# region Chat Completions


class Role(str, Enum):
    ASSISTANT = "assistant"
    DEVELOPER = "developer"
    SYSTEM = "system"
    TOOL = "tool"
    USER = "user"


class ContentPartType(str, Enum):
    TEXT = "text"
    IMAGE = "image_url"


class TextContent(BaseModel):
    type: Literal[ContentPartType.TEXT] = ContentPartType.TEXT
    text: str


class ImageDetail(str, Enum):
    AUTO = "auto"
    LOW = "low"
    HIGH = "high"


class ImageUrl(BaseModel):
    url: str
    detail: ImageDetail = ImageDetail.AUTO


class ImageContent(BaseModel):
    type: Literal[ContentPartType.IMAGE] = ContentPartType.IMAGE
    image_url: ImageUrl


ContentT = TypeVar("ContentT", bound=str | list[TextContent | ImageContent])
RoleT = TypeVar("RoleT", bound=Role)


class BaseMessage(BaseModel, Generic[ContentT, RoleT]):
    content: ContentT
    role: RoleT
    name: str | None = None


class Function(BaseModel):
    name: str
    arguments: dict[str, Any]


class PartialFunction(BaseModel):
    name: str
    arguments: str | dict[str, Any]


class ToolCall(BaseModel):
    id: str
    function: Function
    type: Literal["function"] = "function"


class PartialToolCall(BaseModel):
    id: str | None
    function: PartialFunction
    type: Literal["function"] = "function"


class DeveloperMessage(BaseMessage[str, Literal[Role.DEVELOPER]]):
    role: Literal[Role.DEVELOPER] = Role.DEVELOPER


class SystemMessage(BaseMessage[str, Literal[Role.SYSTEM]]):
    role: Literal[Role.SYSTEM] = Role.SYSTEM


class UserMessage(BaseMessage[str | list[TextContent | ImageContent], Literal[Role.USER]]):
    role: Literal[Role.USER] = Role.USER


class AssistantMessage(BaseMessage[str, Literal[Role.ASSISTANT]]):
    role: Literal[Role.ASSISTANT] = Role.ASSISTANT
    refusal: str | None = None
    tool_calls: list[ToolCall] | None = None


class ToolMessage(BaseMessage[str, Literal[Role.TOOL]]):
    # A tool message's name field will be interpreted as "tool_call_id"
    role: Literal[Role.TOOL] = Role.TOOL


MessageT = AssistantMessage | DeveloperMessage | SystemMessage | ToolMessage | UserMessage

# endregion

# region Routines


class RoutineContext(BaseModel):
    current_document: str
    chat_history: list[MessageT]
    attachments: str = Field(default="")


# endregion

# region Doc Edit

DEFAULT_DOC_EDIT_TASK = """Edit the document according to the conversation history. \
If no additional context is provided, use your internal knowledge. Otherwise, ground your edits on the provided context."""


class MarkdownEditConfig(BaseModel):
    task: str = Field(
        default=DEFAULT_DOC_EDIT_TASK,
        description="A description of the task to be performed.",
    )
    name_model: str = Field(default="gpt-4o-2024-11-20")
    knowledge_cutoff: str = Field(default="2023-10")
    include_examples: bool = Field(default=False)
    change_summary_prefix: str = Field(default="[Document Editor]: ")


class MarkdownEditOutput(BaseModel):
    updated_doc_markdown: str = Field(
        description="The updated document markdown after the skill has been applied. If no changes were made, this will be the same as the input doc_markdown.",
    )
    change_summary: str = Field(
        default="", description="Optional natural language description of the changes that were made to the page."
    )
    output_message: str = Field(
        default="",
        description="Optional message the model can send if something goes wrong, like the if the task or conversation doesn't make sense.",
    )


# endregion
