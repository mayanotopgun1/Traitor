from __future__ import annotations

from mutation_crossfeature.base_mutator import LLMMutatorBase, MutatorMeta, MutationTarget


class AsyncAutoTraitMutator(LLMMutatorBase):
    """Mutator 6: Auto-trait forcing (+Send +Sync)."""

    meta = MutatorMeta(
        key="async_1",
        name="auto_trait_forcing",
        category="async_concurrency",
    )

    system_prompt = """Rust mutator: auto-trait forcing (+Send +Sync).
Do one small local mutation, keep syntax valid, and output only Rust code or NO_MUTATION.
"""

    def build_prompt(self, seed_code: str, target: MutationTarget) -> str:
        return f"""Operator: auto-trait forcing (+Send +Sync).

TARGET_TYPE: {target.type_name}
TARGET_TRAIT: {target.trait_name or 'None'}

Edit only target-related bounds/where clauses.
Add + Send + Sync at one bound site.
Keep edits minimal, local, and syntax-valid.
Avoid broad refactors and renaming/reordering.

Rust seed:
{seed_code}

Return Rust code only.
"""
