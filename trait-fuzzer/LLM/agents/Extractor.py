from ..LLM_connector import LLMConnector

class ExtractorAgent:
    def __init__(self, connector: LLMConnector):
        self.connector = connector
        self.system_prompt = """
        You are an expert Rust compiler developer. Your task is to extract the topological structure 
        of Trait and Type relationships from a given Rust code snippet.
        Focus on:
        1. Trait definitions (supertraits, associated types).
        2. Impl blocks (generic bounds, where clauses).
        3. Struct/Enum definitions involving generics.
        
        Output a concise description of the topology, abstracting away variable names if possible.
        """

    def extract_topology(self, code_snippet: str) -> str:
        prompt = f"Extract topology from the following Rust code:\n\n```rust\n{code_snippet}\n```"
        return self.connector.query(prompt, self.system_prompt)
