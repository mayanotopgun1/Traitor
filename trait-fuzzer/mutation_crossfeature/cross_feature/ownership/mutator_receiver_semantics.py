from __future__ import annotations

from mutation_crossfeature.base_mutator import LLMMutatorBase, MutatorMeta, MutationTarget


class OwnershipReceiverSemanticsMutator(LLMMutatorBase):
    """Mutator 4: Receiver semantics conversion (&self -> self)."""

    meta = MutatorMeta(
        key="ownership_2",
        name="receiver_semantics_conversion",
        category="ownership",
    )

    system_prompt = """Rust mutator: receiver semantics conversion.
Do one small local mutation, keep syntax valid, and output only Rust code or NO_MUTATION.
"""

    def build_prompt(self, seed_code: str, target: MutationTarget) -> str:
        return f"""Operator: receiver semantics conversion.

TARGET_TYPE: {target.type_name}
TARGET_TRAIT: {target.trait_name or 'None'}

Edit only target-related trait/impl methods.
Change one receiver from &self/&mut self to self.
Apply minimal local fixes to keep syntax valid.
Keep edits minimal, local, and avoid renaming/reordering.

Rust seed:
{seed_code}

Return Rust code only.
"""
