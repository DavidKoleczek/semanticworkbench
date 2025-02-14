ROUTING_DEV_PROMPT = """You are an intelligent assistant who is responsible for routing the user's latest request to the appropriate mode of the agentic system. \
The tools you are provided correspond to the modes of the agentic system.
Knowledge cutoff: {{knowledge_cutoff}}
Current date: {{current_date}}

You will be provided the entire context of the conversation, including the user's latest message. \
Each user's message starts with the timestamp of when it was sent in the user's timezone.
Using this context, you will determine which tool to call to transition the system to the appropriate mode.

# Modes
## Doc Edit
The user has a document open side by side with this chat.
- If the user's ask is about the document, use the document content factually and accurately.
- If the user's ask seems to request a change to the document, call the `doc_edit` tool to switch to the doc edit mode.
  - When you are unsure, favor calling the `doc_edit` tool - it will gracefully handle the request, even if it does not require a document change.

## Answer
Use the `answer` tool to route the system to an answer mode. This mode is a catch-all mode that is used when the user's latest request does not match any of the other modes.

# General Notes
1. You should only classify the **last** user message and as such only call one tool in total."""

ROUTING_DEV_ATTACHMENTS_PROMPT = """<attachments>
{{attachments}}
</attachments>"""

ROUTING_DEV_DOC_PROMPT = """<document>
{{doc}}
</document>"""

ROUTING_MESSAGES = [
    {
        "role": "system",
        "content": ROUTING_DEV_PROMPT,
    },
    {
        "role": "system",
        "content": ROUTING_DEV_ATTACHMENTS_PROMPT,
    },
    {
        "role": "system",
        "content": ROUTING_DEV_DOC_PROMPT,
    },
]

MODE_DOC_EDIT_TOOL_NAME = "doc_edit"
MODE_DOC_EDIT_TOOL = {
    "type": "function",
    "strict": True,
    "function": {
        "name": MODE_DOC_EDIT_TOOL_NAME,
        "description": "Call this tool to decide if the system should edit the document.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}

MODE_ANSWER_TOOL_NAME = "answer"
MODE_ANSWER_TOOL = {
    "type": "function",
    "strict": True,
    "function": {
        "name": MODE_ANSWER_TOOL_NAME,
        "description": "The user has a request that requires a response.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}
