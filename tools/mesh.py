import os
from typing import Type, Optional, Any
from pydantic import BaseModel, Field, PrivateAttr
from crewai import LLM
from crewai.tools import BaseTool

from llm_factory import get_llm_factory

# Define the input schema for the tool
class PubMedSubjectSearchBuilderInput(BaseModel):
    """Input schema for PubMedSubjectSearchBuilderTool.

    Carries the raw clinical scenario or question that the tool converts into a
    PubMed Simple Subject Search.
    """

    scenario: str = Field(
        ..., 
        description="The raw clinical scenario or query to convert into a PubMed search."
    )

class PubMedSubjectSearchBuilderTool(BaseTool):
    """CrewAI tool that turns a clinical scenario into a PubMed Simple Subject Search.

    Following NLM Evidence-Based Practice (EBP) guidelines, the tool prompts an
    LLM to (1) frame the scenario as a PICO question, (2) extract the core
    defining keywords while omitting filterable variables (e.g. age groups), and
    (3) format those keywords as a plain, space-separated term list with no MeSH
    tags, punctuation, or Boolean operators — ready to paste into PubMed.

    The LLM is built through the shared :mod:`llm_factory` so the tool inherits
    the service's authentication (LiteLLM proxy + JWT, with fallback) rather than
    requiring a hard-coded OpenAI client. Pass ``jwt_token`` to authenticate the
    call through the proxy like the rest of the service.
    """

    name: str = "PubMed EBP Search Builder"
    description: str = (
        "Translates a clinical scenario into a PubMed Simple Subject Search. "
        "It frames the question using PICO, extracts the core keywords (omitting filterable variables), "
        "and formats them as a plain, space-separated term list with no operators or punctuation."
    )
    args_schema: Type[BaseModel] = PubMedSubjectSearchBuilderInput
    _llm: LLM = PrivateAttr()

    def __init__(self, jwt_token: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        # Build the LLM through the LLM factory so the tool inherits the service's
        # authentication (LiteLLM proxy + JWT, with fallback) instead of a
        # hard-coded direct OpenAI client that requires OPENAI_API_KEY. The model
        # is read from the env (LITELLM_DEFAULT_MODEL, defaults to gpt-4.1). The
        # JWT, when available, lets the call authenticate through the proxy
        # exactly like the rest of the service.
        token = jwt_token.split("Bearer")[1].strip() if jwt_token and "Bearer" in jwt_token else None
        self._llm = get_llm_factory().create_llm(
            jwt_token=token,
            temperature=0,
        )

    def _run(self, scenario: str, *args: Any, **kwargs: Any) -> str:
        prompt = f"""
You are an expert clinical information specialist practicing Evidence-Based Practice (EBP).
Follow the NLM PubMed guidelines precisely to prepare a search from the given clinical scenario.

Clinical Scenario: "{scenario}"

Follow these three steps:

Step 1: Frame the Clinical Question using PICO (per module 02-100)
- Identify the Patient/Problem (P)
- Identify the Intervention (I)
- Identify the Comparison (C) (write "None" or "Not specified" if not applicable)
- Identify the Outcome (O)
- Draft a clear Clinical Question.

Step 2: Identify Search Terms (per module 02-200)
- Pull out the most important defining keywords from your PICO question.
- CRITICAL RULE: Do not include variables that can be filtered later (such as specific age groups like "65 and older", "infants", or "adults") in your search terms. These will be applied as PubMed filters instead.
- List the extracted core keywords.

Step 3: Format Simple Subject Search (per module 03-100)
- Build the search string for PubMed's Simple Subject Search.
- CRITICAL RULE: Enter the key terms with NO tags (like [mesh]), NO punctuation, and NO explicit Boolean operators (do not use "AND"). Just list the key terms separated by spaces.
- Example pattern: "high blood pressure patient education exercise"

Example : 
Physicians in your office recommend exercise to patients age 65 and older who have high blood pressure. However, you overhear patients express doubts. One patient tells his spouse that he does not know how exercise will help. Will patients follow their physicians recommendations for exercise? You are considering whether creating handouts and holding a class on the benefits of physical activity might encourage patients to exercise.

Using PICO, we identify:
P = Patient or Problem - Patients age 65 and older with high blood pressure
I = Intervention - Patient education
C = Comparison - No patient education
O = Outcome - Patient participation in exercise

Formulated Clinical Question:
Are patient education programs effective (compared to no intervention) in increasing patient exercise in the population of patients age 65 and older with high blood pressure?

Key Search Terms:
patient education, exercise, high blood pressure

Simple Subject Search Query:
patient education exercise high blood pressure

Output format:
### 1. PICO Framework
- **P (Patient/Problem):** <value>
- **I (Intervention):** <value>
- **C (Comparison):** <value>
- **O (Outcome):** <value>

### 2. Formulated Clinical Question
<question>

### 3. Key Search Terms
<keywords with explanation of omitted filterable terms if applicable>

### 4. Simple Subject Search Query
<Exactly the space-separated key terms, nothing else>
"""
        messages = [{"role": "user", "content": prompt}]
        try:
            # Using the modern CrewAI LLM call pattern
            response = self._llm.call(messages=messages)
            return response
        except Exception as e:
            return f"Error building PubMed search: {str(e)}"
        

# token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6IkkyRVg2dFVkUnF4cmFDVmZON0lIciJ9.eyJpdmNhcC9jbGFpbXMvZ3JvdXBJZHMiOlsiM2JhZGFkODktYmY1YS00MjAzLTlmOGYtZDVmNTk5MDY3OTZjIl0sImFjYyI6IjNiYWRhZDg5LWJmNWEtNDIwMy05ZjhmLWQ1ZjU5OTA2Nzk2YyIsImlzcyI6Imh0dHBzOi8vaXZhcC5hdS5hdXRoMC5jb20vIiwic3ViIjoib2F1dGgyfEFBRnxjLTVsdEI0a1hYTG5WR0RIanFxRzh4d3FWQWlKemtleWJ6Q2hhXzlRdDlrIiwiYXVkIjpbImh0dHBzOi8vZGV2ZWxvcC5pdmNhcC5uZXQvIiwiaHR0cHM6Ly9pdmFwLmF1LmF1dGgwLmNvbS91c2VyaW5mbyJdLCJpYXQiOjE3ODE2NjI0MDEsImV4cCI6MTc4MTc0ODgwMSwic2NvcGUiOiJvcGVuaWQgcHJvZmlsZSBlbWFpbCBvZmZsaW5lX2FjY2VzcyIsImF6cCI6Ilo3eFI2YTZMcDRBOG5LaGQ1YUF1bDg5Zk1oUmJJMkRtIn0.UwuDTMC5Fju0ZLWRegbMNeWorCg_4GzH_Rlrr0JYsOqkHQkBoBVe-h7-F2P4u-NzIG1Yfr8fjfNwbQraFIz0cT9266H1vD9padGMo9vAhgzk01NkwgOAg0tgjyFju95d28bEVqt_JUycrJBKMfBFM7Bj1p-b27Zmg9aJxYVh4A1DqvIMcGmMAYeH5Wno1UYDvZffH8oYlwuaMfER8Ywa7sU1YmUmae6najzs6fRmXgg1MtlHsnG4pVS2f9bMZrJc6NpnCBCdT29TW0DEJXuV4GbDwVStFdXSIKVx7UrH6tGOufDZIZSPivp7A8SBAyn3XXoycUEmLr4UfjHX-1c8Ww"
# pb_tool = PubMedSubjectSearchBuilderTool(jwt_token=token)
# resp = pb_tool.run("Conduct a comprehensive biomedical patent landscape analysis focusing on small molecule ligands targeting influenza hemagglutinin (HA) for therapeutic purposes. Identify key patent families, prominent inventors, and active companies or research institutions holding these patents over the last 10-15 years. Summarise key claims and provide an overview of the intellectual property landscape.")
# print(resp)
