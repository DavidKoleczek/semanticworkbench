# Copyright (c) Microsoft. All rights reserved.

from typing import Annotated

from content_safety.evaluators import CombinedContentSafetyEvaluatorConfig
from openai_client import AzureOpenAIServiceConfig
from pydantic import BaseModel, Field
from semantic_workbench_assistant.config import UISchema

# The semantic workbench app uses react-jsonschema-form for rendering
# dynamic configuration forms based on the configuration model and UI schema
# See: https://rjsf-team.github.io/react-jsonschema-form/docs/
# Playground / examples: https://rjsf-team.github.io/react-jsonschema-form/

# The UI schema can be used to customize the appearance of the form. Use
# the UISchema class to define the UI schema for specific fields in the
# configuration model.


#
# region Assistant Configuration
#


# the workbench app builds dynamic forms based on the configuration model and UI schema
class AssistantConfigModel(BaseModel):
    aoai_fast_deployment_name: Annotated[
        str,
        Field(
            title="Deployment Name (Fast Model)",
            description="Deployment of a fast model to use. Recommended is to point to gpt-4o-mini-2024-07-18",
        ),
    ] = "gpt-4o-mini"

    aoai_gpt4o_deployment_name: Annotated[
        str,
        Field(
            title="Deployment Name (GPT-4o Model)",
            description="Deployment of a gpt-4o model to use. Recommended is to point to gpt-4o-2024-11-20",
        ),
    ] = "gpt-4o"

    aoai_o3_deployment_name: Annotated[
        str,
        Field(
            title="Deployment Name (o3 Model)",
            description="Deployment of an o3 model to use. Recommended is to point to o3-mini-2025-01-31",
        ),
    ] = "o3-mini"

    service_config: Annotated[
        AzureOpenAIServiceConfig,
        Field(
            title="Azure OpenAI Service Configuration",
            description="Configuration for the Azure OpenAI service. NOTE: The model deployment names in this section will be ignored.",
            default=AzureOpenAIServiceConfig.model_construct(),
        ),
    ]

    content_safety_config: Annotated[
        CombinedContentSafetyEvaluatorConfig,
        Field(
            title="Content Safety Configuration",
        ),
        UISchema(widget="radio"),
    ] = CombinedContentSafetyEvaluatorConfig()


# endregion
