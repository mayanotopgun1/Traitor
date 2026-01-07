import random
from typing import Dict
import logging

class MutatorPool:
    def __init__(self, config: Dict):
        self.logger = logging.getLogger(__name__)
        fuzzer_cfg = config.get("fuzzer", {})

        self.weights = fuzzer_cfg.get("strategy_weights", {
            "ast_structural": 0.4,
            "ast_non_structural": 0.4,
            "llm_injection": 0.2
        })
        self.strategies = list(self.weights.keys())
        self.probs = list(self.weights.values())

        # Sub-weights inside AST-structural strategy.
        # If not provided, keep legacy equal probability among 4 structural mutators.
        self.structural_ops = [
            "add_assoc_type",
            "add_trait",
            "add_impl",
            "constraint_injection",
        ]
        default_structural_subweights = {op: 1.0 for op in self.structural_ops}
        self.structural_subweights = fuzzer_cfg.get(
            "structural_subweights",
            default_structural_subweights,
        )

    def select_strategy(self) -> str:
        """
        Selects a mutation strategy based on configured weights.
        """
        # Top level selection
        strategy = random.choices(self.strategies, weights=self.probs, k=1)[0]
        
        # Sub-selection for AST
        if strategy == "ast_structural":
            weights = [float(self.structural_subweights.get(op, 0.0)) for op in self.structural_ops]
            # If misconfigured (all zeros), fall back to equal weights.
            if not any(w > 0 for w in weights):
                weights = [1.0] * len(self.structural_ops)
            return random.choices(self.structural_ops, weights=weights, k=1)[0]
        if strategy == "ast_non_structural":
            return random.choice([
                "bin_op_flip", 
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
