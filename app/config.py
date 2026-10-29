from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    llm_timeout_s: float = 60.0

    # Resilience. The free tier allowed 5 requests/minute for gemini-3.6-flash on the author's key.
    llm_rpm: int = 5
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

    top_k: int = 5
    max_steps: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
