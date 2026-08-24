"""
agent/db_agent.py

Thin wrapper around the LangGraph DB Agent graph.

Provides the same run() / resume() interface that app.py calls.
Handles:
  - Converting DB history (plain dicts) to LangChain message objects
  - Injecting Langfuse CallbackHandler into graph config
  - Detecting LangGraph interrupt() events (human-in-the-loop approval)
  - Returning a normalized result dict to app.py
"""

import logging
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from db_agent_suite.agent.graph import db_agent_graph
from db_agent_suite.utils.observability import obs_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DBAgent")


# =============================================================
# MESSAGE HELPERS
# =============================================================

def history_to_messages(history: list) -> list[BaseMessage]:
    """
    Convert plain dict conversation history (loaded from PostgreSQL)
    to LangChain message objects for LangGraph.

    Only user/assistant roles are replayed — tool-call chains are
    dropped because they cannot be safely reconstructed across sessions.
    """
    messages = []
    for msg in history:
        if isinstance(msg, BaseMessage):
            if msg.type in ["human", "user"] and msg.content:
                messages.append(msg)
            elif msg.type in ["ai", "assistant"] and msg.content:
                if not getattr(msg, "tool_calls", None):
                    messages.append(msg)
            continue

        role = msg.get("role", "")
        content = msg.get("content", "")
        if role in ["user", "human"] and content.strip():
            messages.append(HumanMessage(content=content))
        elif role in ["assistant", "ai"] and content.strip():
            if "tool_calls" not in msg:
                messages.append(AIMessage(content=content))
    return messages


def get_last_ai_text(messages: list) -> str:
    """Extract the text content from the last AIMessage in the list."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content
    return ""


# =============================================================
# DB AGENT CLASS
# =============================================================

class DBAgent:
    """
    LangGraph-based DB Agent.

    Wraps db_agent_graph (a compiled LangGraph StateGraph) with a
    simple run() / resume() interface that app.py uses.

    Each conversation session maps to a unique thread_id in the
    LangGraph MemorySaver checkpointer.
    """

    def __init__(self, groq_api_key=None, openai_api_key=None):
        from db_agent_suite.gateway.llm_gateway import LLMGateway
        self.gateway = LLMGateway(
            groq_api_key=groq_api_key,
            openai_api_key=openai_api_key
        )

    def run(
        self,
        user_prompt: str,
        session_history: list = None,
        session_id: str = "default_session",
        db_config: dict = None,
        permissions: dict = None,
        available_connections: list = None,
        user_info: dict = None,
    ) -> dict:
        """
        Run the agent for a new user message.
        """
        config = self._build_config(session_id, db_config, permissions, available_connections, user_info)

        # Check if the LangGraph checkpointer already has state for this session
        current_state = db_agent_graph.get_state(config)

        if current_state and current_state.values.get("messages"):
            # State already exists — just send the new user message
            messages = [HumanMessage(content=user_prompt)]
        else:
            # Checkpointer is empty (e.g. server restarted). Load full history from DB.
            messages = history_to_messages(session_history or [])
            messages.append(HumanMessage(content=user_prompt))

        logger.info(f"DBAgent.run() | session={session_id} | messages={len(messages)}")

        try:
            with obs_manager.get_propagate_context(
                session_id=session_id, trace_name="db-agent-run"
            ):
                result = db_agent_graph.invoke(
                    {"messages": messages},
                    config=config,
                )
            return self._parse_result(result)

        except Exception as e:
            logger.error(f"Graph invocation error: {e}")
            return {
                "status": "error",
                "message": f"Agent error: {e}",
                "messages": messages,
            }

    def resume(
        self,
        approved: bool,
        session_id: str = "default_session",
        db_config: dict = None,
        permissions: dict = None,
    ) -> dict:
        """
        Resume the graph after a human-in-the-loop interrupt().
        """
        from langgraph.types import Command

        config = self._build_config(session_id, db_config, permissions)
        logger.info(f"DBAgent.resume() | session={session_id} | approved={approved}")

        try:
            with obs_manager.get_propagate_context(
                session_id=session_id, trace_name="db-agent-resume"
            ):
                result = db_agent_graph.invoke(
                    Command(resume=approved),
                    config=config,
                )
            return self._parse_result(result)
        except Exception as e:
            logger.error(f"Graph resume error: {e}")
            return {
                "status": "error",
                "message": f"Resume error: {e}",
            }

    # ---------------------------------------------------------
    # INTERNALS
    # ---------------------------------------------------------

    def _build_config(
        self,
        session_id: str,
        db_config: dict = None,
        permissions: dict = None,
        available_connections: list = None,
        user_info: dict = None,
    ) -> dict:
        """
        Build the LangGraph invocation config.
        Injects db_config, permissions, available_connections, and user_info
        into the configurable dict so all tools can access them via RunnableConfig.
        """
        config = {
            "configurable": {
                "thread_id":             session_id,
                "db_config":             db_config,
                "permissions":           permissions or {"can_read": True, "can_write": True},
                "available_connections": available_connections or [],
                "user_info":             user_info or {},
            }
        }

        # Add Langfuse tracing callback if available
        langfuse_handler = obs_manager.get_langchain_handler(session_id=session_id)
        if langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        return config

    def _parse_result(self, result: dict) -> dict:
        """
        Convert LangGraph invocation result into the standard
        dict that app.py expects.

        Detects interrupt events (human-in-the-loop approval needed).
        """
        interrupts = result.get("__interrupt__", [])
        if interrupts:
            interrupt_data = interrupts[0].value
            sql = interrupt_data.get("sql", "")
            msg = interrupt_data.get("message", "Approval required.")
            logger.info(f"Graph interrupted for SQL approval: {sql}")
            return {
                "status": "pending_approval",
                "message": f"{msg}\n\n```sql\n{sql}\n```",
                "pending_sql": sql,
                "messages": result.get("messages", []),
            }

        messages = result.get("messages", [])
        last_text = get_last_ai_text(messages)

        if not last_text:
            return {
                "status": "error",
                "message": "Agent completed but returned no text response.",
            }

        return {
            "status": "success",
            "message": last_text,
            "messages": messages,
        }
