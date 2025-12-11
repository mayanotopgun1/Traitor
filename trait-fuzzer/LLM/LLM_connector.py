import os
from typing import Optional, Dict, Any

class LLMConnector:
    def __init__(self, config: Dict):
        self.config = config.get("llm", {})
        self.provider = self.config.get("provider", "mock")
        self.model = self.config.get("model", "gpt-4")
        self.api_key = os.getenv(self.config.get("api_key_env", "OPENAI_API_KEY"))

    def query(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Sends a query to the configured LLM provider.
        """
        if self.provider == "mock":
            return self._mock_response(prompt)
        
        # TODO: Implement OpenAI/Claude/etc. integration
        return ""

    def _mock_response(self, prompt: str) -> str:
        """
        Returns a mock response for testing.
        """
        if "Extract topology" in prompt:
            return "Topology: Trait A -> Trait B"
        return "Mock response"
