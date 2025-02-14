import pathlib
from copy import deepcopy
from typing import Any

from liquid import Template
from pydantic import BaseModel


# helper for loading an include from a text file
def load_text_include(filename) -> str:
    # get directory relative to this module
    directory = pathlib.Path(__file__).parent

    # get the file path for the prompt file
    file_path = directory / "text_includes" / filename

    # read the prompt from the file
    return file_path.read_text()


__all__ = ["load_text_include"]


def _apply_templates(value: Any, variables: dict[str, str]) -> Any:
    """Recursively applies Liquid templating to all string fields within the given value."""
    if isinstance(value, str):
        return Template(value).render(**variables)
    elif isinstance(value, list):
        return [_apply_templates(item, variables) for item in value]
    elif isinstance(value, dict):
        return {key: _apply_templates(val, variables) for key, val in value.items()}
    elif isinstance(value, BaseModel):
        # Process each field in the BaseModel by converting it to a dict,
        # applying templating to its values, and then re-instantiating the model.
        processed_data = {key: _apply_templates(val, variables) for key, val in value.model_dump().items()}
        return value.__class__(**processed_data)
    else:
        return value


def compile_messages(messages: list[dict[str, Any]], variables: dict[str, str]) -> list[dict[str, Any]]:
    """Compiles messages using Liquid templating and the provided variables.
    Calls Template(content_part).render(**variables) on each text content part.

    Args:
        messages: List of dict[str, Any] where content can contain Liquid templates.
        variables: The variables to inject into the templates.

    Returns:
        The same list of messages with the content parts injected with the variables.
    """
    messages_formatted = deepcopy(messages)
    messages_formatted = [_apply_templates(message, variables) for message in messages_formatted]
    return messages_formatted
