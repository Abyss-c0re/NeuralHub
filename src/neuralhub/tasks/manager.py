# src/neuralhub/tasks/manager.py
"""
TaskExecutor — the agentic task orchestration engine (rich version for NeuralHub).

Relocated from NeuralCore.tasks.manager (was TaskManager).
This is the single home for planning, goal-driven execution,
delegated task handling, and parallel dispatch with dependency
resolution.

Inheritance:
    class TaskExecutor(CoreTaskExecutor):
        - Inherits execute_delegated (and any other cooperation-only methods)
          from the slim version in NeuralCore (neuralcore/tasks/executor.py).
        - Adds all planning / goal-driven / dispatch logic that lives only in the hub.

The lightweight Task data model (neuralcore.tasks.task.Task) + task status
management (TaskStatus + start/complete methods) remain in NeuralCore/task.py.

PromptBuilder usage is via the hub's inherited version:
    from neuralhub.utils.prompt_builder import PromptBuilder
This gives us the planning prompts (task_decomposition, step_validation_prompt, ...)
while core keeps only what its own context machinery needs.
"""
import json
import asyncio
from typing import AsyncIterator, Any, Tuple, List, Dict, Optional

from neuralcore.agents.state import AgentState
from neuralcore.tasks.task import Task, TaskStatus
from neuralcore.utils.logger import Logger
from neuralhub.utils.prompt_builder import PromptBuilder

# Reuse the slim TaskExecutor from core (the one that owns execute_delegated
# and the guarantee that task status management lives in core/task.py).
# This eliminates duplication while obeying "no hub imports inside core".
from neuralcore.tasks.executor import TaskExecutor as CoreTaskExecutor

logger = Logger.get_logger()


class TaskExecutor(CoreTaskExecutor):
    """Rich TaskExecutor for NeuralHub (inherits cooperation methods from core).

    Inherits:
      - execute_delegated (the only method the slim core version provides)

    Adds all planning/goal-driven/dispatch logic that lives exclusively in the hub.

    This removes the previous duplicate implementation of execute_delegated.

    DynamicCore integration:
      - When the agent has a dynamic_core, the TaskExecutor can consult it
        during planning and when the agent is stuck in repeated failures.
      - This enables high-level workflow decisions (plan_next_workflow_phase,
        insert_reflection_step, mark_workflow_dead_end, etc.) to influence
        task decomposition and execution strategy.
    """

    def __init__(self, agent):
        self.agent = agent
        self.dynamic_core = getattr(agent, "dynamic_core", None)

    async def plan(self) -> AsyncIterator[Tuple[str, Any]]:
        """Plan a task decomposition using the LLM.

        Yields phase and planning_complete / planning_fallback events.
        Populates agent.state.tasks and related structures.
        """
        logger.info("[PLANNING START] TaskExecutor.plan called")
        yield ("phase_changed", {"phase": "planning"})
        state = self.agent.state

        planning_prompt = PromptBuilder.task_decomposition(state.task)
        plan_text = ""

        try:
            plan_text = await self.agent.client.chat(
                planning_prompt,
                temperature=0.0,
                max_tokens=self.agent.client.max_tokens,
            )
            logger.info(f"[PLANNING RAW] LLM returned {len(plan_text)} chars")

            plan = json.loads(plan_text.strip())
            steps: List[Dict] = plan.get("steps", [])

            # === DynamicCore Integration in Planning ===
            if self.dynamic_core and self.dynamic_core.is_enabled():
                logger.info("[DYNAMIC_CORE] Reviewing LLM plan at high level before task creation")
                # In a more complete version this would call plan_next_workflow_phase or similar.
                # For now we just log that DynamicCore had visibility into the plan.
                # Future: let DynamicCore return suggested phase adjustments.

            if hasattr(self.agent, "consolidator") and self.agent.consolidator:
                for step in steps:
                    suggested = step.get("suggested_tool", "").strip()
                    if suggested:
                        await self.agent.consolidator.record_llm_suggested_tool(
                            query=step.get("description", state.task),
                            tool_name=suggested,
                        )

            logger.info(
                f"[PLANNING] LLM proposed {len(steps)} step(s) for query: {state.task[:80]}..."
            )

            for step in steps:
                expected = step.get("expected_outcome", "")
                if not expected or not str(expected).strip():
                    step["expected_outcome"] = (
                        "Step completed successfully (file located/analyzed/tool added)"
                    )

            if len(steps) <= 1:
                if steps:
                    step0 = steps[0]
                    description = step0.get(
                        "description", state.task or "Single-step goal"
                    )
                    expected_outcome = step0.get(
                        "expected_outcome", "Task completed successfully"
                    )
                else:
                    description = state.task or "Single-step goal"
                    expected_outcome = "Task completed successfully"

                simple_task = Task(
                    description=description,
                    expected_outcome=expected_outcome,
                )
                state.tasks = [simple_task]
                state.root_task = Task(description=state.task or "Root task")
                state.root_task.add_subtask(simple_task)
                state.current_task_index = 0

                logger.info(
                    "[SINGLE-STEP] Plan size=1 → initialized single Task object"
                )
                yield (
                    "planning_complete",
                    {
                        "planned_tasks": state.planned_tasks,
                        "is_single_step": True,
                        "num_steps": 1,
                    },
                )

            else:
                state.build_tasks_from_plan(steps)
                state.current_task_index = 0

                logger.info(
                    f"[MULTI-STEP] Plan size={len(steps)} → created {len(state.tasks)} Task objects"
                )
                for i, task in enumerate(state.tasks):
                    logger.debug(
                        f"  Task {i}: {task.description[:80]}... | expected='{task.expected_outcome}'"
                    )

                yield (
                    "planning_complete",
                    {
                        "planned_tasks": state.planned_tasks,
                        "is_single_step": False,
                        "num_steps": len(steps),
                    },
                )
                logger.info("[PLANNING END] Planning completed successfully")

        except json.JSONDecodeError as e:
            logger.error(f"Planning JSON parse failed: {e}")
            fallback = Task(
                description=state.task, expected_outcome="Task completed successfully"
            )
            state.tasks = [fallback]
            state.root_task = Task(description=state.task)
            state.root_task.add_subtask(fallback)
            state.current_task_index = 0
            yield (
                "planning_fallback",
                {"reason": "JSON parse error", "is_single_step": True},
            )

        except Exception as e:
            logger.error(f"Planning failed: {e}", exc_info=True)
            fallback = Task(
                description=state.task, expected_outcome="Task completed successfully"
            )
            state.tasks = [fallback]
            state.root_task = Task(description=state.task)
            state.root_task.add_subtask(fallback)
            state.current_task_index = 0
            yield ("planning_fallback", {"reason": str(e), "is_single_step": True})

    async def validate(self, task: Optional[Task]) -> bool:
        """Validation logic for a single task (safety wrapper)."""
        if not task or task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            return False
        return True

    async def _validate_task_outcome(self, task: Task, state: AgentState) -> bool:
        """Unified task outcome validation (called for every task).

        Uses the LLM via PromptBuilder.step_validation_prompt.
        Safe fallback for last_tool_success.
        """
        if not task:
            return False

        logger.info(
            f"[TASK VALIDATION] Validating outcome for task: {task.description[:80]}..."
        )

        last_result_str = (
            str(state.tool_results[-1].get("result", ""))
            if state.tool_results
            else "No tool results yet."
        )

        validation_query = PromptBuilder.step_validation_prompt(
            current_task=task,
            last_result_str=last_result_str,
            total_tasks=len(state.tasks),
            current_idx=state.current_task_index,
        )

        try:
            validation_context = await self.agent.context_manager.provide_context(
                query=validation_query,
                max_input_tokens=self.agent.max_tokens * 0.45,
                reserved_for_output=self.agent.client.max_tokens * 0.25,
                include_logs=True,
                chat=False,
                lightweight_agentic=False,
                return_as_string=True,
            )
            validation_result = await self.agent.client.chat(
                validation_context, temperature=0.0, max_tokens=20
            )
            outcome_met = "YES" in validation_result.strip().upper()
            logger.info(f"[TASK VALIDATION] Outcome met: {outcome_met}")
            return outcome_met
        except Exception as e:
            logger.warning(
                f"Validation LLM failed: {e}. Falling back to marker/tool success."
            )
            last_success = getattr(state, "last_tool_success", None)
            return bool(last_success and last_success.get("success"))

    async def execute(
        self, task: Optional[Task], state: AgentState, target_loop: str, **kwargs
    ) -> AsyncIterator[Tuple[str, Any]]:
        """EXECUTES A SINGLE TOOL + VALIDATES RESULTS for one task.

        Focused responsibility:
          - Tool management (load/unload)
          - Context + streaming via client
          - Tool result processing
          - Task.complete() + per-task validation (always)
        Does NOT manage overall index advancement or goal completion
        (those live in run_goal_driven_loop).
        """
        if not await self.validate(task):
            yield ("phase_changed", {"phase": "restarting_loop"})
            state.request_loop_restart(
                reason="validation_failed", target_loop=target_loop
            )
            return

        # === PERSISTENT TOOL MANAGEMENT (single task only) ===
        if task and not state.skip_manager_this_turn and task.suggested_tool:
            last_tool = state.last_used_tool
            if last_tool and last_tool != task.suggested_tool:
                try:
                    self.agent.action_manager.unload_tools([last_tool])
                    logger.debug(f"[TOOL MGMT] Unloaded previous tool: {last_tool}")
                except Exception as e:
                    logger.warning(f"[TOOL MGMT] Failed to unload {last_tool}: {e}")

            if not self.agent.action_manager.is_loaded(task.suggested_tool):
                try:
                    self.agent.action_manager.load_tools([task.suggested_tool])
                    logger.info(
                        f"[TOOL MGMT] Loaded suggested tool for step: {task.suggested_tool}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[TOOL MGMT] Could not pre-load {task.suggested_tool}: {e}"
                    )

        current_query = task.description if task else state.task

        yield ("phase_changed", {"phase": "thinking"})

        if not current_query:
            current_query = await self.agent.wait_for_incoming_message(
                role="user", return_content_only=True
            )
        if not current_query:
            state.request_loop_restart(
                reason="No query detected", target_loop=target_loop
            )
            return

        messages = await self.agent.context_manager.provide_context(
            query=current_query,
            max_input_tokens=self.agent.max_tokens,
            reserved_for_output=self.agent.max_tokens * 0.45,
            include_logs=True,
            chat=False,
            lightweight_agentic=True,
        )

        logger.debug(f"Task Context: {str(messages)}")

        queue = await self.agent.client.stream_with_tools(
            manager=self.agent.action_manager,
            messages=messages,
            temperature=self.agent.temperature,
            max_tokens=self.agent.max_tokens,
            tool_choice="auto",
            auto_stop_on_complete_tool=True,
        )

        text_buffer = ""
        tools_called_this_turn = False
        marker = PromptBuilder.FINAL_ANSWER_MARKER

        try:
            async for kind, payload in self.agent.client._drain_queue(queue):
                if kind == "content":
                    text_buffer += str(payload or "")
                    yield ("content_delta", str(payload or ""))

                elif kind in ("tool_delta", "tool_complete", "needs_confirmation"):
                    tools_called_this_turn = True
                    if isinstance(payload, dict):
                        tool_name = payload.get("tool_name") or payload.get("name")
                        if tool_name:
                            yield ("tool_name", {"name": tool_name})

                        if tool_name and "FindTool" in tool_name:
                            state.record_findtool_call()
                            state.skip_manager_this_turn = True
                            state.request_loop_restart(
                                reason="FindTool called", target_loop=target_loop
                            )
                            yield ("phase_changed", {"phase": "restarting_loop"})
                            return
                        elif tool_name:
                            state.last_used_tool = tool_name

                elif kind == "finish":
                    break
                elif kind in ("error", "cancelled"):
                    yield kind, payload
                    return
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield "error", str(e)
            return

        if not state.skip_manager_this_turn:
            state.skip_manager_this_turn = False

        final_reply = text_buffer.strip()
        has_marker = marker in final_reply
        if has_marker:
            final_reply = final_reply.replace(marker, "").strip()

        # ====================== SINGLE-TASK COMPLETION + VALIDATION ======================
        last_success = getattr(state, "last_tool_success", None)
        tool_reported_success = bool(last_success and last_success.get("success"))
        strong_completion = has_marker or tool_reported_success

        if tools_called_this_turn and task:
            result = (
                state.tool_results[-1].get("result") if state.tool_results else None
            )
            tool_name = state.last_used_tool
            task.used_tool = tool_name

            if hasattr(self.agent, "consolidator") and self.agent.consolidator:
                success = bool(result) and task.status != TaskStatus.FAILED
                await self.agent.consolidator.record_actual_tool_usage(
                    query=task.description, tool_name=tool_name, success=success
                )

            task.complete(result=result)
            if task.status == TaskStatus.COMPLETED:
                state.completed_task_ids.add(task.task_id)

        # Always validate the task outcome
        validated = False
        if task and (tools_called_this_turn or strong_completion):
            validated = await self._validate_task_outcome(task, state)
            if validated:
                logger.info("[TASK VALIDATION PASSED] Task validated")
                if task.status != TaskStatus.FAILED:
                    task.status = TaskStatus.COMPLETED
                    state.completed_task_ids.add(task.task_id)
            else:
                logger.warning("[TASK VALIDATION FAILED] Outcome not met")
                state.increment_empty_loop()

        # ====================== PER-TURN SAFETY (anti-repeat, empty loop, action restart) ======================
        action_restart_triggered = False
        action_continuation = None

        if not has_marker:
            lines = final_reply.splitlines()
            last_100_lines = "\n".join(lines[-100:])
            last_100_lower = last_100_lines.lower()
            for kw in ["next action:", "next action", "action:", "action"]:
                pos = last_100_lower.rfind(kw)
                if pos != -1:
                    candidate = last_100_lines[pos + len(kw) :].strip()
                    if candidate and len(candidate) > 15:
                        action_continuation = candidate
                        action_restart_triggered = True
                        break

        if action_restart_triggered and action_continuation:
            state.increment_action_restart()
            if state.action_restarts > 3:
                # === DynamicCore Integration Point (repeated action failures) ===
                if self.dynamic_core and self.dynamic_core.is_enabled():
                    logger.info("[DYNAMIC_CORE] Repeated action failures detected → high-level workflow decision recommended")
                    self.dynamic_core.maybe_replan(
                        trigger="repeated_action_failures",
                        task=getattr(state, "task", ""),
                        failure_context=f"action_restarts={state.action_restarts}"
                    )
                    state.request_loop_restart(
                        reason="DynamicCore replan requested after repeated action failures",
                        target_loop=target_loop
                    )
                    yield ("phase_changed", {"phase": "restarting_loop"})
                    return

                state.mark_goal_achieved("Max action restarts reached")
                state.request_loop_stop(
                    reason="Max action restarts reached", target_loop=target_loop
                )
            else:
                state.request_loop_restart(
                    reason="Action restart requested", target_loop=target_loop
                )
                yield ("phase_changed", {"phase": "restarting_loop"})

        if (
            not tools_called_this_turn
            and not has_marker
            and not action_restart_triggered
        ):
            state.increment_empty_loop()
            if state.empty_loops >= 5:
                # === DynamicCore Integration Point ===
                if self.dynamic_core and self.dynamic_core.is_enabled():
                    logger.info("[DYNAMIC_CORE] Agent stuck in empty loops → triggering high-level replan")
                    self.dynamic_core.maybe_replan(
                        trigger="task_stuck_empty_loops",
                        task=getattr(state, "task", ""),
                        failure_context=f"empty_loops={state.empty_loops}"
                    )
                    # Surface the decision tools more strongly in next context
                    state.request_loop_restart(
                        reason="DynamicCore high-level replan requested due to empty loops",
                        target_loop=target_loop
                    )
                    yield ("phase_changed", {"phase": "restarting_loop"})
                    return

                state.mark_goal_achieved("Forced completion after empty loops")
                state.request_loop_stop(
                    reason="Forced completion after empty loops",
                    target_loop=target_loop,
                )
            else:
                state.request_loop_restart(
                    reason="Empty loop continuation", target_loop=target_loop
                )
                yield ("phase_changed", {"phase": "restarting_loop"})
        else:
            state.empty_loops = 0

        # Yield final task result event so run_goal_driven_loop can react
        yield (
            "task_result",
            {
                "task_id": getattr(task, "task_id", None),
                "success": bool(task and task.status == TaskStatus.COMPLETED),
                "tools_called": tools_called_this_turn,
                "strong_completion": strong_completion,
                "validated": validated,
            },
        )

    async def run_goal_driven_loop(
        self, state: AgentState, target_loop: str, **kwargs
    ) -> AsyncIterator[Tuple[str, Any]]:
        """CLEAN GOAL-DRIVEN LOOP ORCHESTRATOR.

        Delegates execution to .execute (single task/tool + validation).
        Manages steps: if validated → advance or complete goal.
        """
        state.increment_loop()

        current_task: Optional[Task] = state.get_current_task()

        # Execute the current task (single tool + validation)
        async for event in self.execute(current_task, state, target_loop, **kwargs):
            yield event

        # === STEP MANAGEMENT (if validated → move on) ===
        if current_task and current_task.status == TaskStatus.COMPLETED:
            is_last_task = state.current_task_index >= len(state.tasks) - 1

            if is_last_task:
                state.full_reply = (
                    f"Task completed successfully. {PromptBuilder.FINAL_ANSWER_MARKER}"
                )
                state.is_complete = True
                state.last_tool_success = {"success": True}
                state.mark_goal_achieved("All sub-tasks completed")
                yield (
                    "llm_response",
                    {
                        "full_reply": state.full_reply,
                        "tool_calls": [],
                        "is_complete": True,
                    },
                )
                yield ("phase_changed", {"phase": "completed"})
                state.goal_achieved = True
            else:
                # Advance to next task
                state.current_task_index += 1
                if hasattr(state, "advance_to_next_ready_task"):
                    state.advance_to_next_ready_task()
                logger.info(
                    f"[ADVANCE] Sub-task {state.current_task_index} ready → next"
                )
                yield ("phase_changed", {"phase": "restarting_loop"})
                state.request_loop_restart(
                    reason="Task completed — advancing to next sub-task",
                    target_loop=target_loop,
                )

        elif not state.goal_reached:
            logger.warning(
                "Loop iteration ended without goal_achieved — forcing restart"
            )
            state.request_loop_restart(
                reason="Loop ended without goal", target_loop=target_loop
            )
            yield ("phase_changed", {"phase": "restarting_loop"})

    # ====================== COOPERATIVE TASK EXECUTION ======================
    #
    # execute_delegated is inherited from CoreTaskExecutor (neuralcore/tasks/executor.py).
    # This removes the previous duplication while keeping the cooperation method
    # available to both the slim core path and the rich hub path.

    async def dispatch_parallel(
        self,
        tasks: List[Task],
        agents: List[Any],
        timeout: Optional[float] = None,
    ) -> AsyncIterator[Tuple[str, Any]]:
        """Dispatch tasks to agents respecting dependencies.

        Tasks without dependencies are dispatched immediately in parallel.
        Tasks with dependencies wait for their prerequisites to complete
        before being dispatched.

        Yields events as tasks start, complete, and as all work finishes.
        """
        if not tasks or not agents:
            yield ("dispatch_error", {"reason": "No tasks or agents provided"})
            return

        # Map task_id -> Task for dependency lookup
        task_map: Dict[str, Task] = {t.task_id: t for t in tasks}
        completed_ids: set = set()
        pending: List[Task] = list(tasks)
        running: Dict[str, asyncio.Task] = {}  # task_id -> asyncio.Task
        agent_idx = 0

        yield (
            "dispatch_started",
            {"total_tasks": len(tasks), "total_agents": len(agents)},
        )

        while pending or running:
            # Find ready tasks (all dependencies met)
            newly_ready = []
            still_pending = []
            for task in pending:
                if task.is_ready(completed_ids):
                    newly_ready.append(task)
                else:
                    still_pending.append(task)
            pending = still_pending

            # Dispatch ready tasks to available agents
            for task in newly_ready:
                target_agent = agents[agent_idx % len(agents)]
                agent_idx += 1

                requesting_agent = self.agent

                async def _run_delegated(t=task, a=target_agent):
                    await requesting_agent.request_agent(a, t)
                    # Use a fresh (rich) executor for the target; execute_delegated is inherited from core.
                    await TaskExecutor(a).execute_delegated(t)

                atask = asyncio.create_task(
                    _run_delegated(),
                    name=f"dispatch_{task.task_id[:8]}",
                )
                running[task.task_id] = atask

                yield (
                    "task_dispatched",
                    {
                        "task_id": task.task_id,
                        "description": task.description[:80],
                        "agent": target_agent.name,
                    },
                )

            if not running:
                # No running tasks and no newly ready — possible deadlock
                if pending:
                    yield (
                        "dispatch_error",
                        {
                            "reason": "Dependency deadlock: pending tasks have unmet dependencies",
                            "pending_ids": [t.task_id for t in pending],
                        },
                    )
                break

            # Wait for any running task to complete
            done, _ = await asyncio.wait(
                running.values(),
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if not done and timeout:
                # Timeout — cancel remaining
                for atask in running.values():
                    atask.cancel()
                yield (
                    "dispatch_timeout",
                    {"timeout": timeout, "still_running": list(running.keys())},
                )
                break

            # Process completed tasks
            finished_ids = []
            for atask in done:
                for tid, rt in running.items():
                    if rt is atask:
                        finished_ids.append(tid)
                        break

            for tid in finished_ids:
                atask = running.pop(tid)
                task = task_map[tid]
                completed_ids.add(tid)

                # Check for exceptions
                exc = atask.exception() if atask.done() else None
                if exc:
                    task.complete(error=str(exc))
                    yield (
                        "task_failed",
                        {
                            "task_id": tid,
                            "error": str(exc),
                        },
                    )
                else:
                    yield (
                        "task_completed",
                        {
                            "task_id": tid,
                            "status": task.status.value,
                            "result_preview": str(task.result)[:200]
                            if task.result
                            else None,
                        },
                    )

        yield (
            "dispatch_finished",
            {
                "total_completed": len(completed_ids),
                "total_tasks": len(tasks),
            },
        )
