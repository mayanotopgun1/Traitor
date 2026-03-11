from __future__ import annotations

from mutation_crossfeature.base_mutator import LLMMutatorBase, MutatorMeta, MutationTarget


class ConstAssocInjectionMutator(LLMMutatorBase):
    """Mutator 8: Associated-constant injection with local use."""

    meta = MutatorMeta(
        key="const_1",
        name="associated_constant_injection",
        category="const_generics",
    )

    system_prompt = """Rust mutator: associated-constant injection.
Do one small local mutation, keep syntax valid, and output only Rust code or NO_MUTATION.
"""

    def build_prompt(self, seed_code: str, target: MutationTarget) -> str:
        return f"""Operator: associated-constant injection.

TARGET_TYPE: {target.type_name}
TARGET_TRAIT: {target.trait_name or 'None'}

Edit only target-related trait/use sites.
Add one associated constant and one local usage that depends on it.
Keep edits minimal, local, and syntax-valid.
Avoid broad refactors and renaming/reordering.

Rust seed:
{seed_code}

Return Rust code only.
"""
