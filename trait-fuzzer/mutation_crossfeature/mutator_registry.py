from __future__ import annotations

from typing import Dict, List

from LLM import LLMConnector
from mutation_crossfeature.cross_feature.async_concurrency import AsyncAutoTraitMutator, AsyncContextWrapMutator
from mutation_crossfeature.cross_feature.const_generics import ConstAssocInjectionMutator
from mutation_crossfeature.cross_feature.lifetime import LifetimeBorrowMutator, LifetimeHigherRankMutator
from mutation_crossfeature.cross_feature.ownership import (
    OwnershipDropInjectionMutator,
    OwnershipPointerWrapMutator,
    OwnershipReceiverSemanticsMutator,
)


def build_mutators(connector: LLMConnector) -> Dict[str, object]:
    instances = [
        LifetimeBorrowMutator(connector),
        LifetimeHigherRankMutator(connector),
        OwnershipPointerWrapMutator(connector),
        OwnershipReceiverSemanticsMutator(connector),
        OwnershipDropInjectionMutator(connector),
        AsyncAutoTraitMutator(connector),
        AsyncContextWrapMutator(connector),
        ConstAssocInjectionMutator(connector),
    ]
    return {m.meta.key: m for m in instances}


def default_operator_keys() -> List[str]:
    return [
        "lifetime_1",
        "lifetime_2",
        "ownership_1",
        "ownership_2",
        "ownership_3",
        "async_1",
        "async_2",
        "const_1",
    ]
