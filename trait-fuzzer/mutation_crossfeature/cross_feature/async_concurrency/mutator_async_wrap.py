from __future__ import annotations

from mutation_crossfeature.base_mutator import LLMMutatorBase, MutatorMeta, MutationTarget


class AsyncContextWrapMutator(LLMMutatorBase):
    """Mutator 7: Immediate async context wrapping."""

    meta = MutatorMeta(
        key="async_2",
        name="async_context_wrapping",
        category="async_concurrency",
    )

    system_prompt = """Rust mutator: async context wrapping.
Do one small local mutation, keep syntax valid, and output only Rust code or NO_MUTATION.
Only mutate when an async context already exists; do not introduce invalid `.await` usage.
"""

    def build_prompt(self, seed_code: str, target: MutationTarget) -> str:
        return f"""Operator: async context wrapping.

TARGET_TYPE: {target.type_name}
TARGET_TRAIT: {target.trait_name or 'None'}

Edit only target-related code.
    Only apply if the seed already has `async fn` or an existing async block.
    Wrap one target-related statement block inside that existing async context.
    Do not add `.await` in non-async functions.
    If no safe async context exists, return NO_MUTATION.
Keep edits minimal, local, and syntax-valid.
Avoid broad refactors and renaming/reordering.

Rust seed:
{seed_code}

Return Rust code only.
"""
