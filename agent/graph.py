"""
agent/graph.py

LangGraph StateGraph definition for the DB Agent.

Graph topology:
    START
      └─> guardrail_node   (prompt injection check)
            └─> agent_node  (LLM reasoning via ChatLiteLLM / LiteLLM gateway)
                  └─> tools_node  (execute tool calls)
                        └─> agent_node  (loop until no more tool calls)
                  └─> END  (when LLM returns a text response with no tool calls)

State:
    Uses LangGraph's built-in MessagesState:
        messages: list[BaseMessage]  ← append-only, managed by LangGraph

Human-in-the-loop:
    modify_db tool calls interrupt() which pauses the graph.
    app.py resumes with graph.invoke(Command(resume=True/False), config).

Checkpointer:
    MemorySaver keeps per-thread state so the graph can be resumed
    after a human-in-the-loop interruption.

Observability:
    Langfuse CallbackHandler is passed via config["callbacks"] at invoke time.
    It automatically traces every node, every LLM call, and every tool execution.
"""

import logging
import os
from typing import Literal

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from db_agent_suite.agent.tools import TOOLS
from db_agent_suite.gateway.guardrails import check_prompt_safety, SecurityException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DBAgentGraph")

# =============================================================
# SYSTEM PROMPT
# =============================================================

def build_system_prompt(permissions: dict) -> str:
    base_prompt = """You are a PostgreSQL Database Assistant with the following tools:

QUERY TOOLS (use these to read/write data):
  - list_tables          → list all tables in the CURRENT active database
  - get_schema(table)    → get column definitions for a table
  - query_db(sql)        → execute a SELECT query (read-only)
  - modify_db(sql)       → execute INSERT/UPDATE/DELETE (requires user approval)
  - create_table(sql)    → execute CREATE/ALTER/DROP TABLE (requires user approval)

CONNECTION TOOLS (use these to manage which database is active):
  - add_database_connection  → create and save a new DB connection when given credentials (host/port/db/user/pass)
  - connect_to_database      → connect/switch to a database by name and get an instant schema overview
  - switch_database          → same as connect_to_database (use when user says "switch to X")
  - list_available_databases → show all databases the user can access

Rules:
- When the user mentions a database name (e.g. "use sales DB", "switch to analytics", "connect to X"), ALWAYS call connect_to_database or switch_database FIRST.
- After connect_to_database / switch_database succeeds, all subsequent list_tables / query_db calls will automatically target the new database.
- Explore schema before querying if columns/tables are unknown.
- Write valid PostgreSQL queries only.
- Fix SQL errors automatically and retry.
- Be concise but thorough.

When results have numerical/categorical data suitable for a chart, append a ```chart code block after your table:
```chart
{"type":"bar","title":"Title","labels":["A","B"],"datasets":[{"label":"Series","data":[1,2]}]}
```
Supported types: bar, line, pie, scatter.
"""
    allowed = permissions.get("allowed_tables")
    if allowed is not None:
        base_prompt += f"\nRESTRICTED to tables: {', '.join(allowed)}. Refuse queries on any other table."
    return base_prompt

# =============================================================
# BUILD LLM
# =============================================================

def _build_llm_with_tools():
    """
    Build a ChatLiteLLM instance with all tools bound.
    ChatLiteLLM routes through LiteLLM under the hood, so:
      - LiteLLM Router fallbacks are active
      - LiteLLM Redis caching is active
    Fallback: primary → fallback model via LangChain .with_fallbacks()
    """
    from langchain_litellm import ChatLiteLLM

    groq_api_key = os.getenv("GROQ_API_KEY")

    llm_primary = ChatLiteLLM(
        model="groq/openai/gpt-oss-120b",
        api_key=groq_api_key,
        temperature=0.1,
    )
    llm_fallback = ChatLiteLLM(
        model="groq/openai/gpt-oss-20b",
        api_key=groq_api_key,
        temperature=0.1,
    )

    # LangChain-level fallback (in addition to LiteLLM's own router fallback)
    llm = llm_primary.with_fallbacks([llm_fallback])
    return llm.bind_tools(TOOLS)


# =============================================================
# GRAPH NODES
# =============================================================

def guardrail_node(state: MessagesState) -> dict:
    """
    Security check node. Runs before the agent sees any user message.
    If the latest human message is a prompt injection attempt, this node
    injects a rejection AIMessage and routes to END (skipping the LLM entirely).
    """
    # Find the latest human message to check
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        None,
    )
    if not last_human:
        return {}

    groq_api_key = os.getenv("GROQ_API_KEY", "")
    try:
        check_prompt_safety(last_human.content, groq_api_key)
        logger.info("Guardrail: prompt passed safety check.")
        return {}  # State unchanged — proceed to agent_node
    except SecurityException as e:
        logger.warning(f"Guardrail blocked prompt: {e}")
        # Inject a refusal message and the router will END the graph
        return {
            "messages": [
                AIMessage(
                    content=f"⛔ Request blocked by security guardrail: {e}",
                    name="guardrail",
                )
            ]
        }


from langchain_core.runnables.config import RunnableConfig

def agent_node(state: MessagesState, config: RunnableConfig) -> dict:
    """
    LLM reasoning node. Calls the LLM with the full message history.
    The LLM either:
      a) Returns a text response → graph routes to END
      b) Returns tool_calls       → graph routes to tools_node
    """
    # If last message is already a guardrail refusal, don't call LLM
    last_msg = state["messages"][-1] if state["messages"] else None
    if last_msg and isinstance(last_msg, AIMessage) and last_msg.name == "guardrail":
        return {}

    # Build message list: system prompt + history
    permissions = config.get("configurable", {}).get("permissions", {})
    system_prompt = build_system_prompt(permissions)
    messages = [SystemMessage(content=system_prompt)] + state["messages"]

    llm_with_tools = _build_llm_with_tools()
    logger.info(f"Agent node: calling LLM with {len(messages)} messages...")

    try:
        response = llm_with_tools.invoke(messages)
        logger.info(f"Agent node: LLM responded (tool_calls={bool(response.tool_calls)})")
        return {"messages": [response]}
    except Exception as e:
        logger.error(f"Agent node LLM error: {e}")
        return {
            "messages": [AIMessage(content=f"I encountered an error: {e}")]
        }


# =============================================================
# ROUTING LOGIC
# =============================================================

def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:
    """
    Conditional edge: decides whether to call a tool or end the graph.
    - If the last AI message has tool_calls → route to tools_node
    - Otherwise → END
    - If last message is a guardrail refusal → END immediately
    """
    last_msg = state["messages"][-1]

    # Guardrail refusal
    if isinstance(last_msg, AIMessage) and last_msg.name == "guardrail":
        return "__end__"

    # Tool calls present → run tools
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        return "tools"

    # No tool calls → final answer
    return "__end__"


# =============================================================
# BUILD GRAPH
# =============================================================

def build_graph():
    """
    Assemble and compile the LangGraph StateGraph.

    Returns the compiled graph with:
      - MemorySaver checkpointer (enables interrupt/resume for approval flow)
      - Interrupt support in ToolNode for human-in-the-loop modify_db calls
    """
    # Tool node executes whatever tool the LLM called
    tool_node = ToolNode(TOOLS)

    # Build the graph
    builder = StateGraph(MessagesState)

    # Add nodes
    builder.add_node("guardrail", guardrail_node)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tool_node)

    # Edges
    builder.add_edge(START, "guardrail")
    builder.add_edge("guardrail", "agent")
    builder.add_conditional_edges("agent", should_continue)
    builder.add_edge("tools", "agent")  # After tools run, always go back to agent

    # Compile with memory checkpointer (required for interrupt/resume)
    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)

    logger.info("LangGraph DB Agent graph compiled successfully.")
    return graph


# =============================================================
# SINGLETON GRAPH INSTANCE
# =============================================================

db_agent_graph = build_graph()
