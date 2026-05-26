"""Hub-level PromptBuilder.

All agentic task-related prompt methods used by the rich TaskExecutor
(task_decomposition, step_validation_prompt, delegated_task_prompt,
FINAL_ANSWER_MARKER, lightweight_agentic_context, objective_reminder, etc.)
are available here.

Planning-related prompts (task_decomposition, step_validation_prompt, etc.)
have their canonical source in this file (relocated from core's PromptBuilder
as part of the "everything planning related should be in hub" cleanup).

Core's PromptBuilder keeps only the prompts its own context machinery
still needs (lightweight_agentic_context, objective_reminder, etc.) plus
cooperation prompts needed by the slim core TaskExecutor (delegated_task_prompt).

This satisfies both "migrate the relevant prompt builder methods by using
inheritance in hub" and "relocate relevant prompts ... to the hub".
"""
from neuralcore.utils.prompt_builder import PromptBuilder as CorePromptBuilder


class PromptBuilder(CorePromptBuilder):
    """Prompt builder for NeuralHub / agentic task execution flows.

    Inherits the non-planning prompts from core.
    Planning-related prompts are defined here as the canonical home.
    """

    # --- Relocated planning prompts (source moved here) ---

    @staticmethod
    def task_decomposition(original_query: str) -> str:
        """Pragmatic task decomposition (relocated to hub)."""
        from neuralcore.actions.registry import registry
        available_tools = registry.list_all_tools(
            limit=None,
            include_hidden=False,
            as_llm_format=False,
            include_schema=False,
        )
        tools_section = ""
        if available_tools:
            sorted_tools = sorted(available_tools, key=lambda t: (t.get("set_name", ""), t.get("name", "")))
            tools_list = []
            for tool in sorted_tools:
                name = tool.get("name", "unknown")
                set_name = tool.get("set_name", "UnknownSet")
                desc = (tool.get("description", "") or "").strip()[:160]
                if desc and not desc.endswith("."):
                    desc += "."
                tools_list.append(f"• {name} [{set_name}] → {desc}")
            tools_text = "\n".join(tools_list)
            tools_section = f"""
    CURRENTLY AVAILABLE TOOLS (full list — use these exact tools whenever possible):

    {tools_text}

    You MUST prefer these real tools. Only suggest a step that cannot be fulfilled by any of them if absolutely necessary.
    """
        else:
            tools_section = "\nNo tools are currently registered in the system."

        return f"""You are a pragmatic task decomposition expert.

USER REQUEST: {original_query}

{tools_section}

Break this request into the **minimal number of clear, actionable steps** required to complete the goal.

Core Rules (strict):
- Output **EXACTLY 1 step** ONLY if the entire request can be completed with a **single tool call or single atomic action** with no real dependencies.
- Output **2 or more steps** whenever the request contains **sequential phases**, **different capabilities**, or **hard dependencies**.
- Each step must correspond to what **one realistic tool execution** can achieve.

Output ONLY valid JSON:
{{
"steps": [
    {{
    "description": "exact sub-task description",
    "dependencies": [list of previous step indices or empty list],
    "suggested_tool": "exact tool name if available, otherwise short category hint",
    "expected_outcome": "short, realistic success description"
    }}
]
}}
Return the plan:"""

    @staticmethod
    def step_validation_prompt(
        current_task: "Task",
        last_result_str: str,
        total_tasks: int,
        current_idx: int,
    ) -> str:
        """Strict LLM-based step outcome validation prompt (relocated to hub)."""
        return f"""You are a strict validation agent for multi-step task execution.

CURRENT SUB-TASK ({current_idx + 1}/{total_tasks}):
{current_task.description}

EXPECTED OUTCOME THAT MUST BE VERIFIED:
{current_task.expected_outcome or "Step completed successfully"}

MOST RECENT TOOL RESULT:
{last_result_str or "No tool results available yet."}

QUESTION:
Has the expected outcome been FULLY achieved based on the tool result above?
Be conservative. Only answer YES if the outcome is clearly and completely met.

Answer with **exactly one word** on its own line:
YES
or
NO

No explanations. No extra text."""


# Re-export the constant
FINAL_ANSWER_MARKER = CorePromptBuilder.FINAL_ANSWER_MARKER
