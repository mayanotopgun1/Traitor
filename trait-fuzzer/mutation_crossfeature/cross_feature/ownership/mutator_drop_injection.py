from __future__ import annotations

from mutation_crossfeature.base_mutator import LLMMutatorBase, MutatorMeta, MutationTarget


class OwnershipDropInjectionMutator(LLMMutatorBase):
    """Mutator 5: Empty Drop impl injection."""

    meta = MutatorMeta(
        key="ownership_3",
        name="drop_impl_injection",
        category="ownership",
    )

    system_prompt = """Rust mutator: empty Drop impl injection.
Do one small local mutation, keep syntax valid, and output only Rust code or NO_MUTATION.
"""

    def build_prompt(self, seed_code: str, target: MutationTarget) -> str:
        return f"""Operator: empty Drop impl injection.

TARGET_TYPE: {target.type_name}
TARGET_TRAIT: {target.trait_name or 'None'}

Edit only target-related code.
Inject one empty impl Drop for TARGET_TYPE (or closest concrete target form).
Keep edits minimal, local, and syntax-valid.
Avoid broad refactors and renaming/reordering.

Rust seed:
{seed_code}

Return Rust code only.
"""
