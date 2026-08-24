"""
Observability module - Langfuse Python SDK v4.14.4

Langfuse v4 uses OpenTelemetry under the hood.
API reference confirmed from installed package:

  get_client()
    .start_as_current_observation(*, name, as_type, input, output, metadata,
                                   model, model_parameters, ...)
    .start_observation(...)          -- imperative, must call .end()
    .set_current_trace_io(*)
    .flush()
    .auth_check()

  propagate_attributes(*, session_id, user_id, tags, trace_name, ...)
    -- sets trace-level metadata for all observations in the context block

  CallbackHandler(*, public_key=None, trace_context=None)
    -- LangChain/LangGraph native integration (reads env vars automatically)

Tracing architecture:
  Primary path (LangGraph agent):
      config={"callbacks": [CallbackHandler()]} -> full trace tree auto-created
        - guardrail_node
        - agent_node (LLM generations with tokens)
        - tool_node (tool calls)

  Secondary path (direct LiteLLM gateway completions):
      Manual spans/generations via start_as_current_observation()
"""

import logging
import threading
import uuid
import time
from contextlib import contextmanager
from db_agent_suite import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Observability")


class ObservabilityManager:
    """
    Langfuse v4.14.4 observability manager.

    Singleton usage: obs_manager = ObservabilityManager() at module level.
    """

    def __init__(self):
        self._client = None
        self.active = False
        self._last_host = None
        self.setup()

    # ---------------------------------------------------------
    # INITIALIZATION
    # ---------------------------------------------------------

    def setup(self):
        """
        Initialize the Langfuse v4 client via get_client().
        Initializes the Langfuse client if API keys are available in config.
        Re-initializes when credentials change (e.g. sidebar key update).
        """
        public_key = config.LANGFUSE_PUBLIC_KEY
        secret_key = config.LANGFUSE_SECRET_KEY
        host = config.LANGFUSE_HOST or "https://cloud.langfuse.com"

        if not public_key or not secret_key:
            self.active = False
            logger.info("Langfuse keys not found. Observability running in MOCK mode.")
            return

        try:
            from langfuse import get_client
            self._client = get_client()
            self._last_host = host
            self.active = True
            logger.info(f"Langfuse v4 client initialized. Host: {host}")
        except Exception as e:
            self.active = False
            self._client = None
            logger.error(f"Failed to initialize Langfuse: {e}")

    # ---------------------------------------------------------
    # CONNECTION CHECK
    # ---------------------------------------------------------

    def check_connection(self) -> tuple:
        """
        Verify the Langfuse server connection via auth_check().
        Returns (is_ok: bool, message: str).
        """
        self.setup()
        if not self.active or not self._client:
            return False, "Langfuse client not initialized (missing keys or init error)"
        try:
            ok = self._client.auth_check()
            if ok:
                return True, f"Successfully authenticated — Host: {self._last_host}"
            return False, "Auth check returned False (check credentials)"
        except Exception as e:
            return False, f"Auth check failed: {e}"

    # ---------------------------------------------------------
    # LANGCHAIN / LANGGRAPH CALLBACK HANDLER  (primary path)
    # ---------------------------------------------------------

    def get_langchain_handler(self, session_id: str = None):
        """
        Return a Langfuse v4 CallbackHandler for LangGraph tracing.

        v4.14.4 documented pattern:
            from langfuse import get_client
            from langfuse.langchain import CallbackHandler
            from langfuse import propagate_attributes

            langfuse = get_client()
            handler = CallbackHandler()

        Inject into LangGraph:
            with propagate_attributes(session_id=session_id, trace_name="db-agent"):
                result = graph.invoke(state, config={"callbacks": [handler]})

        This auto-traces:
          - Every LangGraph node (guardrail, agent, tools)
          - Every LLM call (model, token counts, latency)
          - Every tool invocation (name, input, output)

        Returns None in MOCK mode for graceful degradation.
        """
        self.setup()
        if not self.active:
            logger.info("Langfuse inactive — no LangChain handler created.")
            return None
        try:
            from langfuse.langchain import CallbackHandler
            # v4.14.4 signature: CallbackHandler(*, public_key=None, trace_context=None)
            # Reads env vars automatically — no credentials passed explicitly.
            handler = CallbackHandler()
            logger.info(f"Langfuse CallbackHandler created (session={session_id})")
            return handler
        except Exception as e:
            logger.error(f"Failed to create Langfuse CallbackHandler: {e}")
            return None

    def get_propagate_context(self, session_id: str = None, user_id: str = None,
                               trace_name: str = "db-agent", tags: list = None):
        """
        Return a propagate_attributes context manager for setting trace-level
        metadata (session_id, user_id, tags) on the LangGraph invocation.

        v4.14.4 signature:
            propagate_attributes(*, session_id, user_id, tags, trace_name, ...)

        Usage in db_agent.py:
            handler = obs_manager.get_langchain_handler(session_id)
            prop_ctx = obs_manager.get_propagate_context(session_id=session_id)

            with prop_ctx:
                result = graph.invoke(state, config={"callbacks": [handler]})
        """
        self.setup()
        if not self.active:
            from contextlib import nullcontext
            return nullcontext()
        try:
            from langfuse import propagate_attributes
            kwargs = {"trace_name": trace_name}
            if session_id:
                kwargs["session_id"] = session_id
            if user_id:
                kwargs["user_id"] = user_id
            if tags:
                kwargs["tags"] = tags
            return propagate_attributes(**kwargs)
        except Exception as e:
            logger.error(f"Failed to build propagate_attributes context: {e}")
            from contextlib import nullcontext
            return nullcontext()

    # ---------------------------------------------------------
    # MANUAL SPAN  (secondary path — direct gateway completions)
    # ---------------------------------------------------------

    @contextmanager
    def span(self, name: str, input_data=None, output_data=None,
             metadata: dict = None, as_type: str = "span"):
        """
        Create a manual observation span using Langfuse v4.

        v4.14.4 API:
            with client.start_as_current_observation(
                name=name,
                as_type="span",  # or "tool", "chain", "guardrail", etc.
                input=input_data,
                metadata=metadata,
            ) as span:
                span.update(output=output_data)

        Falls back to MOCK logging when Langfuse is inactive.
        """
        if not self.active or not self._client:
            logger.info(f"[Span MOCK] {as_type}:{name}")
            yield None
            return

        kwargs = {"name": name, "as_type": as_type}
        if input_data is not None:
            kwargs["input"] = input_data
        if metadata is not None:
            kwargs["metadata"] = metadata

        try:
            with self._client.start_as_current_observation(**kwargs) as span_obj:
                yield span_obj
                if output_data is not None:
                    try:
                        span_obj.update(output=output_data)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Error in span '{name}': {e}")
            yield None

    # ---------------------------------------------------------
    # MANUAL GENERATION  (LLM call inside gateway)
    # ---------------------------------------------------------

    @contextmanager
    def generation(self, name: str, model: str = None, input_data=None,
                   output_data=None, model_parameters: dict = None,
                   metadata: dict = None):
        """
        Create a manual LLM generation observation using Langfuse v4.

        v4.14.4 API:
            with client.start_as_current_observation(
                name=name,
                as_type="generation",
                model=model,
                input=input_data,
                model_parameters=model_parameters,
                metadata=metadata,
            ) as gen:
                gen.update(output=output_data)

        Falls back to MOCK logging when Langfuse is inactive.
        """
        if not self.active or not self._client:
            logger.info(f"[Generation MOCK] Start: {name} | Model: {model}")
            yield None
            logger.info(f"[Generation MOCK] End: {name}")
            return

        kwargs = {"name": name, "as_type": "generation"}
        if model is not None:
            kwargs["model"] = model
        if input_data is not None:
            kwargs["input"] = input_data
        if model_parameters is not None:
            kwargs["model_parameters"] = model_parameters
        if metadata is not None:
            kwargs["metadata"] = metadata

        try:
            with self._client.start_as_current_observation(**kwargs) as gen_obj:
                yield gen_obj
                if output_data is not None:
                    try:
                        gen_obj.update(output=output_data)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Error in generation '{name}': {e}")
            yield None

    # ---------------------------------------------------------
    # UPDATE helper
    # ---------------------------------------------------------

    def update(self, obs_obj, output_data=None, metadata=None,
               level=None, status_message=None):
        """
        Update an observation object (span or generation) in-place.
        v4.14.4 update() signature:
            obs.update(*, output, metadata, level, status_message, ...)
        No-ops silently if obs_obj is None (MOCK mode).
        """
        if not obs_obj:
            return
        try:
            kwargs = {}
            if output_data is not None:
                kwargs["output"] = output_data
            if metadata is not None:
                kwargs["metadata"] = metadata
            if level is not None:
                kwargs["level"] = level
            if status_message is not None:
                kwargs["status_message"] = status_message
            if kwargs:
                obs_obj.update(**kwargs)
        except Exception as e:
            logger.error(f"Error updating observation: {e}")

    # ---------------------------------------------------------
    # FLUSH
    # ---------------------------------------------------------

    def flush(self):
        """
        Flush all buffered Langfuse OTel spans to the server immediately.
        Call this after agent turn or direct gateway completion.
        """
        if self.active and self._client:
            try:
                self._client.flush()
                logger.info("Langfuse events flushed successfully.")
            except Exception as e:
                logger.error(f"Failed to flush Langfuse: {e}")
        else:
            logger.info("Langfuse inactive. Nothing to flush.")


# =============================================================
# GLOBAL SINGLETON
# =============================================================

obs_manager = ObservabilityManager()
