import os
import logging
import litellm

from litellm import Router

from db_agent_suite import config
from db_agent_suite.cache.redis_client import cache_client
from db_agent_suite.utils.observability import obs_manager


# =============================================================
# LOGGING
# =============================================================

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("LLMGateway")


# =============================================================
# FALLBACK EVENTS
# =============================================================

fallback_events = []


def record_failure_callback(
    exception,
    kwargs,
    start_time,
    end_time,
):
    """
    LiteLLM failure callback.

    Records failed model calls so the UI can display
    fallback information.
    """

    model_name = kwargs.get(
        "model",
        "unknown",
    )

    error_msg = str(exception)

    logger.warning(
        f"LiteLLM call failed for model "
        f"{model_name}: {error_msg}"
    )

    event = {
        "failed_model": model_name,
        "error": error_msg,
        "timestamp": (
            start_time.isoformat()
            if hasattr(start_time, "isoformat")
            else str(start_time)
        ),
    }

    fallback_events.append(event)


# =============================================================
# REGISTER LITELLM FAILURE CALLBACK
# =============================================================

if record_failure_callback not in litellm.failure_callback:

    litellm.failure_callback.append(
        record_failure_callback
    )


# =============================================================
# LANGFUSE OBSERVABILITY SETUP
# =============================================================

def setup_langfuse_observability():
    """
    Configure LiteLLM to log completions to Langfuse via the built-in
    callback. Langfuse v2 SDK is fully compatible with this callback
    (it has the langfuse.version.__version__ attribute LiteLLM needs).

    Also initialises the obs_manager singleton for manual traces.
    """
    public_key = config.LANGFUSE_PUBLIC_KEY
    secret_key = config.LANGFUSE_SECRET_KEY
    host = config.LANGFUSE_HOST

    if public_key and secret_key:
        logger.info(f"Langfuse observability enabled on host: {host} (tracing from outside)")
    else:
        logger.warning("Langfuse keys missing. Tracing will run in MOCK mode.")


# =============================================================
# LLM GATEWAY
# =============================================================

class LLMGateway:
    """
    LLM Gateway.

    Responsibilities:

    - LiteLLM Router
    - Model fallbacks
    - Redis/local caching
    - Langfuse tracing
    - Failure logging
    """

    def __init__(
        self,
        groq_api_key=None,
        openai_api_key=None,
    ):

        # ---------------------------------------------------------
        # API KEYS
        # ---------------------------------------------------------

        self.groq_api_key = (
            groq_api_key
            or config.GROQ_API_KEY
        )

        self.openai_api_key = (
            openai_api_key
            or config.OPENAI_API_KEY
        )

        # ---------------------------------------------------------
        # Langfuse
        # ---------------------------------------------------------

        setup_langfuse_observability()

        # ---------------------------------------------------------
        # Router
        # ---------------------------------------------------------

        self.router = (
            self._initialize_router()
        )

        # ---------------------------------------------------------
        # Cache
        # ---------------------------------------------------------

        self._configure_caching()

    # =========================================================
    # INITIALIZE ROUTER
    # =========================================================

    def _initialize_router(self) -> Router:

        model_list = []

        # =====================================================
        # GROQ MODELS
        # =====================================================

        if self.groq_api_key:

            # -------------------------------------------------
            # PRIMARY
            # -------------------------------------------------

            model_list.append({

                "model_name": "primary-model",

                "litellm_params": {

                    "model":
                        "groq/openai/gpt-oss-120b",

                    "api_key":
                        self.groq_api_key,
                }
            })

            # -------------------------------------------------
            # FALLBACK 1
            # -------------------------------------------------

            model_list.append({

                "model_name":
                    "fallback-model-1",

                "litellm_params": {

                    # IMPORTANT:
                    # GPT-OSS is hosted by Groq.
                    # Therefore explicitly use groq/.
                    "model":
                        "groq/openai/gpt-oss-20b",

                    "api_key":
                        self.groq_api_key,
                }
            })

        # =====================================================
        # OPENAI
        # =====================================================

        elif self.openai_api_key:

            model_list.append({

                "model_name":
                    "openai-primary",

                "litellm_params": {

                    "model":
                        "openai/gpt-4o-mini",

                    "api_key":
                        self.openai_api_key,
                }
            })

        # =====================================================
        # NO KEYS
        # =====================================================

        if not model_list:

            logger.warning(
                "No API keys provided. "
                "Creating dummy router."
            )

            model_list.append({

                "model_name":
                    "primary-model",

                "litellm_params": {

                    "model":
                        "openai/gpt-oss-120b",

                    "api_key":
                        "dummy",
                }
            })

        # =====================================================
        # FALLBACK RULES
        # =====================================================

        fallback_rules = {}

        # -----------------------------------------------------
        # Primary → Groq GPT-OSS
        # -----------------------------------------------------

        if self.groq_api_key:

            fallback_rules[
                "primary-model"
            ] = [
                "fallback-model-1"
            ]

        # -----------------------------------------------------
        # Primary → OpenAI
        # -----------------------------------------------------

        if self.openai_api_key:

            if "primary-model" not in fallback_rules:

                fallback_rules[
                    "primary-model"
                ] = []

            fallback_rules[
                "primary-model"
            ].append(
                "openai-primary"
            )

        # -----------------------------------------------------
        # OpenAI → Groq
        # -----------------------------------------------------

        if (
            self.openai_api_key
            and self.groq_api_key
        ):

            fallback_rules[
                "openai-primary"
            ] = [
                "fallback-model-1"
            ]

        logger.info(
            f"Configured {len(model_list)} models."
        )

        logger.info(
            f"Fallback rules: "
            f"{fallback_rules}"
        )

        # =====================================================
        # ROUTER
        # =====================================================

        return Router(

            model_list=model_list,

            routing_strategy="simple-shuffle",

            fallbacks=[
                fallback_rules
            ],

            # Don't waste tokens retrying a rate-limited model.
            # Move immediately to fallback.
            num_retries=0,
        )

    # =========================================================
    # CACHE
    # =========================================================

    def _configure_caching(self):

        try:

            if cache_client.is_mock:

                logger.info(
                    "Setting LiteLLM cache "
                    "to local memory."
                )

                litellm.cache = (
                    litellm.Cache(
                        type="local"
                    )
                )

            else:

                logger.info(
                    "Setting LiteLLM cache "
                    f"to Redis at "
                    f"{cache_client.host}:"
                    f"{cache_client.port}"
                )

                litellm.cache = (
                    litellm.Cache(

                        type="redis",

                        host=cache_client.host,

                        port=cache_client.port,

                        password=cache_client.password,
                    )
                )

        except Exception as e:

            logger.exception(
                f"Failed to configure "
                f"LiteLLM cache: {e}"
            )

    # =========================================================
    # LANGCHAIN / LANGGRAPH INTEGRATION
    # =========================================================

    def get_chat_model(self, tools: list = None):
        """
        Return a LangChain-compatible ChatLiteLLM instance.

        ChatLiteLLM routes through LiteLLM under the hood, so:
          - LiteLLM Redis caching is automatically active
          - LiteLLM Langfuse callbacks are active
          - Model is the same primary groq model as the Router

        If `tools` is provided, returns llm.bind_tools(tools) so
        LangGraph's ToolNode can dispatch tool calls.

        Used by agent/graph.py agent_node().
        """
        try:
            from langchain_litellm import ChatLiteLLM

            llm_primary = ChatLiteLLM(
                model="groq/openai/gpt-oss-120b",
                api_key=self.groq_api_key,
                temperature=0.1,
            )
            llm_fallback = ChatLiteLLM(
                model="groq/openai/gpt-oss-20b",
                api_key=self.groq_api_key,
                temperature=0.1,
            )

            # LangChain-level fallback chains on top of LiteLLM's router fallback
            llm = llm_primary.with_fallbacks([llm_fallback])

            if tools:
                return llm.bind_tools(tools)
            return llm

        except Exception as e:
            logger.error(f"Failed to build ChatLiteLLM: {e}")
            raise

    # =========================================================
    # COMPLETION (LiteLLM Router — unchanged)
    # =========================================================

    def completion(
        self,
        messages,
        tools=None,
        tool_choice=None,
        temperature=0.2,
        **kwargs,
    ):

        # -----------------------------------------------------
        # SELECT STARTING MODEL GROUP
        # -----------------------------------------------------

        model = "primary-model"

        if (
            self.openai_api_key
            and not self.groq_api_key
        ):

            model = "openai-primary"

        logger.info(
            f"Starting completion with "
            f"model group: {model}"
        )

        # =====================================================
        # WRAP IN A LANGFUSE SPAN (v4 root observation)
        # =====================================================

        with obs_manager.span(
            name="llm-gateway-request",
            input_data={
                "messages": messages,
                "tool_count": len(tools) if tools else 0,
                "requested_model": model,
            },
        ):

            response = None

            try:

                # =================================================
                # LLM GENERATION
                # =================================================

                with obs_manager.generation(

                    name="llm-completion",

                    model=model,

                    input_data={
                        "messages": messages,
                        "tools": tools,
                        "tool_choice": tool_choice,
                    },

                    model_parameters={
                        "temperature": temperature,
                    },

                ) as generation:

                    # =============================================
                    # LITELLM
                    # =============================================

                    response = (
                        self.router.completion(

                            model=model,

                            messages=messages,

                            tools=tools,

                            tool_choice=tool_choice,

                            temperature=temperature,

                            caching=True,

                            **kwargs,
                        )
                    )

                    # Update generation with structured output
                    try:
                        out = {
                            "role": response.choices[0].message.role,
                            "content": (response.choices[0].message.content or "")[:500],
                            "model": response.model,
                            "finish_reason": response.choices[0].finish_reason,
                            "usage": {
                                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                                "total_tokens": response.usage.total_tokens if response.usage else 0,
                            },
                        }
                    except Exception:
                        out = {"raw": "(could not parse response)"}
                    obs_manager.update(generation, output_data=out)

                return response

            except Exception as e:

                logger.exception(f"LLM completion failed: {e}")
                raise

            finally:

                obs_manager.flush()


    # =========================================================
    # FALLBACK LOGS
    # =========================================================

    def get_fallback_logs(self):

        global fallback_events

        return list(
            fallback_events
        )

    # =========================================================
    # CLEAR FALLBACK LOGS
    # =========================================================

    def clear_fallback_logs(self):

        global fallback_events

        fallback_events.clear()