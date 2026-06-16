"""Test fixtures for services — set dummy API keys to avoid OpenAI client init errors."""

import os

# AsyncOpenAI client requires a non-empty api_key or OPENAI_API_KEY env var.
os.environ.setdefault("DEEPSEEK_API_KEY", "test-dummy-key")
