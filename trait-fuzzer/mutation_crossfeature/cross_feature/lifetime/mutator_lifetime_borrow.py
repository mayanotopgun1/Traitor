from __future__ import annotations

from mutation_crossfeature.base_mutator import LLMMutatorBase, MutatorMeta, MutationTarget


class LifetimeBorrowMutator(LLMMutatorBase):
    """LLM-driven lifetime mutator.

    Mutator 1: 局部借用转换
    - 不改动全局类型定义；优先修改局部变量绑定或函数签名
    - 将按值传递改成显式借用（如 &'a mut T / &'a T）
    - 在涉及投影/归一化上下文时尽量引入借用，提升 borrow checker 与 trait solver 交互压力
    """

    meta = MutatorMeta(
        key="lifetime_1",
        name="local_borrow_conversion",
        category="lifetime",
    )

    system_prompt = """Rust mutator: local borrow conversion.
Do one small local mutation, keep syntax valid, and output only Rust code or NO_MUTATION.
"""

    def build_prompt(self, seed_code: str, target: MutationTarget) -> str:
        return f"""Operator: local borrow conversion.

TARGET_TYPE: {target.type_name}
TARGET_TRAIT: {target.trait_name or 'None'}

Edit only target-related code.
Convert one by-value flow to a borrow (&T or &mut T), preferably in function signature or local binding.
Make minimal follow-up edits to keep syntax valid.
Keep edits local and minimal, and avoid renaming/reordering.

Rust seed:
{seed_code}

Return Rust code only.
"""
