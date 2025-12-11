import random
from typing import List, Dict, Optional
import logging

class MutatorPool:
    def __init__(self, config: Dict):
        self.logger = logging.getLogger(__name__)
        self.weights = config.get("fuzzer", {}).get("strategy_weights", {
            "ast_structural": 0.4,
            "ast_non_structural": 0.4,
            "llm_injection": 0.2
        })
        self.strategies = list(self.weights.keys())
        self.probs = list(self.weights.values())

    def select_strategy(self) -> str:
        """
        Selects a mutation strategy based on configured weights.
        """
        # Top level selection
        strategy = random.choices(self.strategies, weights=self.probs, k=1)[0]
        
        # Sub-selection for AST
        if strategy == "ast_structural":
            return random.choice([
                "type_erasure", 
                "supertrait_expansion", 
                "where_clause_expansion",
                "trait_item_removal",
                "add_assoc_type",
                "type_overwriting",
                "generic_narrowing",
                "add_trait",
                "add_generic_type"
            ])
        if strategy == "ast_non_structural":
            return random.choice([
                "bin_op_flip", 
                "type_erasure", 
                "int_literal_change",
                "bool_flip",
                "replace_by_constant",
                "inject_control_flow"
            ])
            
        return strategy

    def update_weights(self, feedback: Dict):
        """
        Dynamic weight adjustment based on feedback (e.g., success rate, complexity gain).
        TODO: Implement Multi-Armed Bandit or similar adaptive logic.
        """
        pass
