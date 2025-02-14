from typing import Any

import pendulum
from pydantic import BaseModel, Field, PrivateAttr

from assistant.helpers import compile_messages
from assistant.prompts.doc_edit import DOC_EDIT_CHANGES_MESSAGES, DOC_EDIT_MESSAGES
from assistant.response.response_openai import OpenAIResponseProvider

DEFAULT_DOC_EDIT_TASK = """Edit the document according to the conversation history. \
If no additional context is provided, use your internal knowledge. Otherwise, ground your edits on the provided context."""


class DocEditSkillConfig(BaseModel):
    name_model: str = Field(default="gpt-4o-2024-11-20")
    knowledge_cutoff: str = Field(default="2023-10")
    include_examples: bool = Field(default=False)
    use_o_model: bool = Field(default=False)
    change_summary_prefix: str = Field(default="[Document Editor]: ")


class DocEditSkillDefinition(BaseModel):
    doc_markdown: str = Field(description="Markdown representation of the current document")
    task: str = Field(
        default=DEFAULT_DOC_EDIT_TASK,
        description="A description of the task to be performed.",
    )
    conversation_history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Conversation history that provides context for what how the caller wants the document to be edited.",
    )
    context: str = Field(
        default="",
        description="Any additional context for the task, such as attachments.",
    )


class DocEditSkillOutput(BaseModel):
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


class DocEditSkill:
    definition: DocEditSkillDefinition
    config: DocEditSkillConfig = Field(default_factory=DocEditSkillConfig)
    _client: Any = PrivateAttr()

    def __init__(
        self,
        definition: DocEditSkillDefinition,
        skill_config: DocEditSkillConfig,
        response_provider: OpenAIResponseProvider,
    ) -> None:
        self.skill_config = skill_config
        self.response_provider = response_provider
        self.definition = definition

    async def run(self) -> DocEditSkillOutput:
        conv_history = ""
        for msg in self.definition.conversation_history:
            conv_history += f"{msg['role']}: {msg['content']}\n"
        conv_history = conv_history.strip()

        doc_edit_messages = compile_messages(
            messages=DOC_EDIT_MESSAGES,
            variables={
                "knowledge_cutoff": self.skill_config.knowledge_cutoff,
                "current_date": pendulum.now().format("YYYY-MM-DD"),
                "task": self.definition.task,
                "context": self.definition.context,
                "document": self.definition.doc_markdown,
                "conversation_history": conv_history,
            },
        )

        kwargs = {
            "messages": doc_edit_messages,
            "model": self.skill_config.name_model,
            "temperature": 0.3,
            "max_completion_tokens": 4000,
        }

        doc_edit_response = await self.response_provider.chat_completion(**kwargs)
        updated_doc_markdown = doc_edit_response.choices[0].message.content

        if self.definition.doc_markdown != updated_doc_markdown:
            change_summary_messages = compile_messages(
                messages=DOC_EDIT_CHANGES_MESSAGES,
                variables={"before_doc": self.definition.doc_markdown, "after_doc": updated_doc_markdown},
            )
            change_summary_kwargs = {
                "messages": change_summary_messages,
                "model": self.skill_config.name_model,
                "temperature": 0.3,
                "max_completion_tokens": 1000,
            }
            change_summary_response = await self.response_provider.chat_completion(**change_summary_kwargs)
            change_summary = (
                self.skill_config.change_summary_prefix + change_summary_response.choices[0].message.content
            )
        else:
            change_summary = ""

        return DocEditSkillOutput(
            updated_doc_markdown=updated_doc_markdown,
            change_summary=change_summary,
            output_message="",
        )
