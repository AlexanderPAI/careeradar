from backend.config import cfg
from backend.llm_providers.base import LLMAdapter
from backend.llm_providers.gigachat import GigaChatAdapter
from backend.llm_providers.openrouter import OpenRouterAdapter


def create_llm_adapter() -> LLMAdapter:
    """Create the default LLM adapter selected by LLM_PROVIDER."""
    if cfg.llm_provider == "gigachat":
        return GigaChatAdapter(
            gigachat_url=cfg.gigachat_url,
            gigachat_key=cfg.gigachat_key,
            model=cfg.gigachat_model,
            verify_ssl_certs=cfg.gigachat_verify_ssl_certs,
            ca_bundle_files=(
                cfg.gigachat_root_ca_file,
                cfg.gigachat_sub_ca_file,
            ),
        )

    return OpenRouterAdapter(
        openrouter_url="https://openrouter.ai/api/v1/chat/completions",
        openrouter_key=cfg.openrouter_key,
        model="z-ai/glm-5.2",
    )
