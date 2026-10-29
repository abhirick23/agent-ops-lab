from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


# Free-tier requests/minute measured on the author's key by `scripts.probe_limits`
# (results/free_tier_limits.json). Google does not publish these per model.
MEASURED_RPM = {
    "gemini-3.6-flash": 5,
    "gemini-3.5-flash": 5,
    "gemini-3-flash-preview": 5,
    "gemini-3.1-flash-lite": 15,
}
UNKNOWN_MODEL_RPM = 5  # conservative


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"
    llm_timeout_s: float = 60.0

    # Resilience. Unset LLM_RPM => use the measured limit for gemini_model.
    llm_rpm: int | None = None
    llm_max_retries: int = 4
    llm_retry_base_delay: float = 1.0
    llm_cache_enabled: bool = False
    llm_cache_dir: str = "data/llm_cache"

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chroma_dir: str = "data/chroma"
    collection_name: str = "papers"
    corpus_path: str = "data/corpus.jsonl"

    use_reranker: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    prompt_version: str = "v1"  # prompts/<version>.txt
    top_k: int = 5
    max_steps: int = 5

    @property
    def effective_rpm(self) -> int:
        return self.llm_rpm or MEASURED_RPM.get(self.gemini_model, UNKNOWN_MODEL_RPM)


@lru_cache
def get_settings() -> Settings:
    return Settings()
