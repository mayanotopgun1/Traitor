from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from LLM import LLMConnector


@dataclass(frozen=True)
class MutatorMeta:
    key: str
    name: str
    category: str


@dataclass(frozen=True)
class MutationTarget:
    type_name: str
    trait_name: Optional[str] = None


class LLMMutatorBase:
    meta: MutatorMeta
    system_prompt: str

    def __init__(self, connector: LLMConnector):
        self.connector = connector

    def build_prompt(self, seed_code: str, target: MutationTarget) -> str:
        raise NotImplementedError

    def mutate(self, seed_code: str, target: MutationTarget) -> Optional[str]:
        prompt = (
            self.build_prompt(seed_code, target)
            + "\n\nGlobal rules:"
            + "\n- Edit only code related to TARGET_TYPE/TARGET_TRAIT."
            + "\n- When you mutate a site, also apply necessary corresponding adjustments so the code stays consistent."
            + "\n- Keep Rust syntax valid."
            + "\n- Output only Rust code (no markdown fences)."
            + "\n- If not applicable, return NO_MUTATION."
        )
        try:
            response = self.connector.query(prompt, system_prompt=self.system_prompt)
        except Exception:
            return None

        if response is None:
            return None

        cleaned = response.strip()
        if cleaned.startswith("```rust"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        if cleaned == "NO_MUTATION":
            return None
        return cleaned or None
