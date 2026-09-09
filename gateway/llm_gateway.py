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


def _format_proxy_model(name: str) -> str:
    """
    Ensure the model name is prefixed with 'openai/' so LiteLLM client
    routes through the proxy's /chat/completions endpoint rather than
    interpreting provider prefixes (like groq/, meta-llama/) directly.
    """
    if not name:
        return ""
    if name.startswith("openai/"):
        return name
    return f"openai/{name}"


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

    def __init__(self):
        """
        All LLM calls route exclusively through the self-hosted LiteLLM Proxy.
        Two virtual keys control access to two model groups:
          - LITELLM_LOCAL_API_KEY  → local models (Qwen 2.5, Llama Guard)
          - LITELLM_ONLINE_API_KEY → online fallback models (Groq)
        """
        setup_langfuse_observability()
        self.router = self._initialize_router()
        self._configure_caching()

    # =========================================================
    # INITIALIZE ROUTER
    # =========================================================

    def _initialize_router(self) -> Router:
        """
        Build a LiteLLM Router where all models are accessed through
        the self-hosted LiteLLM proxy using two virtual keys:
          primary-model    → LOCAL_CHAT_MODEL  (local virtual key)
          fallback-model-1 → ONLINE_FALLBACK_MODEL_1 (online virtual key)
          fallback-model-2 → ONLINE_FALLBACK_MODEL_2 (online virtual key)
        """
        proxy_url = config.LITELLM_PROXY_BASE_URL
        local_key = config.LITELLM_LOCAL_API_KEY
        online_key = config.LITELLM_ONLINE_API_KEY

        if not proxy_url:
            logger.warning("LITELLM_PROXY_BASE_URL not set. Creating dummy router.")
            return Router(
                model_list=[{
                    "model_name": "primary-model",
                    "litellm_params": {"model": "openai/dummy", "api_key": "dummy"}
                }],
                routing_strategy="simple-shuffle",
                num_retries=0,
            )

        model_list = [
            # 1. Primary: GPT-OSS 120B (Online)
            {
                "model_name": "primary-model",
                "litellm_params": {
                    "model": _format_proxy_model(config.ONLINE_FALLBACK_MODEL_1),
                    "api_base": proxy_url,
                    "api_key": online_key or "sk-dummy",
                },
            },
        ]

        fallback_rules = {}

        # 2. Secondary (Fallback 1): GPT-OSS 20B (Online)
        if online_key and config.ONLINE_FALLBACK_MODEL_2:
            model_list.append({
                "model_name": "fallback-model-1",
                "litellm_params": {
                    "model": _format_proxy_model(config.ONLINE_FALLBACK_MODEL_2),
                    "api_base": proxy_url,
                    "api_key": online_key,
                },
            })

        fallback_rules["primary-model"] = [
            m["model_name"] for m in model_list if m["model_name"] != "primary-model"
        ]

        logger.info(f"Configured {len(model_list)} models via LiteLLM Proxy ({proxy_url})")
        logger.info(f"Fallback rules: {fallback_rules}")

        return Router(
            model_list=model_list,
            routing_strategy="simple-shuffle",
            fallbacks=[fallback_rules] if fallback_rules else [],
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
            from db_agent_suite import config

            proxy_url = config.LITELLM_PROXY_BASE_URL
            local_key = config.LITELLM_LOCAL_API_KEY
            online_key = config.LITELLM_ONLINE_API_KEY

            if not proxy_url:
                raise ValueError("LITELLM_PROXY_BASE_URL is not configured.")

            # 1. PRIMARY: GPT-OSS 120B (Online via LiteLLM Proxy)
            logger.info(f"Primary LLM: {config.ONLINE_FALLBACK_MODEL_1} via LiteLLM Proxy ({proxy_url})")
            llm_primary = ChatLiteLLM(
                model=_format_proxy_model(config.ONLINE_FALLBACK_MODEL_1),
                api_base=proxy_url,
                api_key=online_key or "sk-dummy",
                temperature=0.1,
            )

            fallbacks = []

            # 2. SECONDARY (Fallback 1): GPT-OSS 20B (Online via LiteLLM Proxy)
            if online_key and config.ONLINE_FALLBACK_MODEL_2:
                logger.info(f"Fallback 1 (Secondary): {config.ONLINE_FALLBACK_MODEL_2} via LiteLLM Proxy")
                fallbacks.append(
                    ChatLiteLLM(
                        model=_format_proxy_model(config.ONLINE_FALLBACK_MODEL_2),
                        api_base=proxy_url,
                        api_key=online_key,
                        temperature=0.1,
                    )
                )

            llm = llm_primary.with_fallbacks(fallbacks) if fallbacks else llm_primary

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

        # All calls start on primary-model; the Router handles fallbacks.
        model = "primary-model"

        logger.info(f"Starting completion with model group: {model}")

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


# =============================================================
# SINGLETON INSTANCE
# =============================================================
llm_gateway = LLMGateway()