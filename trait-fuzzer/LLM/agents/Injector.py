from ..LLM_connector import LLMConnector

class InjectorAgent:
    def __init__(self, connector: LLMConnector):
        self.connector = connector
        self.system_prompt = """
        You are an expert Rust fuzzer. Your task is to inject a specific high-risk topological structure 
        into a provided seed code.
        
        You will receive:
        1. Seed Rust code.
        2. Description of the topology to inject.
        
        Rules:
        - Preserve the original logic where possible, or replace it meaningfully.
        - Ensure the resulting code is syntactically correct (it may fail type checking, that's okay/expected).
        - Focus on complex trait bounds, HRTB, and GATs if the topology suggests it.
        """

    def inject_topology(self, seed_code: str, topology_desc: str) -> str:
        prompt = f"""
        Seed Code:
        ```rust
        {seed_code}
        ```
        
        Topology to Inject:
        {topology_desc}
        
        Output the mutated Rust code.
        """
        return self.connector.query(prompt, self.system_prompt)
