import json
import random
import re
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from LLM import LLMConnector

from .compiler_utils import compile_code, is_expected_fail_seed
from .fewshot_pool import FewShotPool
from .prompts import feature_select_prompt, repair_prompt, stage1_prompt, stage2_prompt
from .tsa import TSAMeter


def _strip_code_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```rust"):
        s = s[7:]
    elif s.startswith("```"):
        s = s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


def _strip_rust_comments(code: str) -> str:
    text = code or ""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(?m)//.*$", "", text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(lines).strip()


@dataclass
class TraitorRunResult:
    stage1_output_code: str
    output_code: str
    stage: str
    tsa_original: int
    tsa_output: int
    delta_tsa: int
    accepted_by_tsa: bool
    selected_feature: str
    applied_feature: str
    candidate_features: List[str]
    expected_fail_seed: bool
    tsa_method: str
    tsa_compiler_mode: int
    stage1_tsa: int
    stage2_tsa: int
    stage1_accepted_by_tsa: bool
    stage2_accepted_by_tsa: bool
    feature_applied: bool
    stage1_compile_status: str
    stage2_compile_status: str
    stage2_attempted: bool
    final_compile_status: str
    eligible_for_seed: bool
    stage1_eligible_for_pool: bool
    stage2_eligible_for_pool: bool


class TraitorAgent:
    def __init__(self, full_config: Dict, project_root: Optional[Path] = None):
        self.full_config = dict(full_config or {})
        self.agent_cfg = self.full_config.get("traitor_agent", {})
        self.project_root = Path(project_root or Path(__file__).resolve().parents[1])

        self.repair_iters = int(self.agent_cfg.get("repair_max_iters", 2))
        self.baseline_shots = int(self.agent_cfg.get("baseline_shots", 2))
        self.experience_shots = int(self.agent_cfg.get("experience_shots", 2))
        self.verbose = bool(self.agent_cfg.get("verbose", True))
        self.abort_on_crash_hang = bool(self.agent_cfg.get("abort_on_crash_hang", True))

        llm_cfg = self.full_config.get("llm", {})
        self.connector = LLMConnector({"llm": llm_cfg})

        rustc_cmd = self.agent_cfg.get("rustc_cmd") or self.full_config.get("compiler", {}).get("rustc_cmd") or ["rustc"]
        if isinstance(rustc_cmd, str):
            rustc_cmd = [rustc_cmd]

        tsa_extra_args = self.agent_cfg.get("tsa_extra_args", [])
        self.tsa_meter = TSAMeter(
            rustc_cmd=list(rustc_cmd),
            project_root=self.project_root,
            use_script=bool(self.agent_cfg.get("tsa_use_utils_script", True)),
            compiler_mode=int(self.agent_cfg.get("tsa_compiler_mode", 1)),
            extra_args=list(tsa_extra_args),
            timeout_sec=int(self.agent_cfg.get("tsa_timeout_sec", 20)),
        )

        compile_extra_args = self.agent_cfg.get("compile_extra_args", [])
        self.compile_cmd = list(rustc_cmd)
        self.compile_extra_args = list(compile_extra_args)
        self.compile_timeout_sec = int(self.agent_cfg.get("compile_timeout_sec", 20))

        pool_dir = self.agent_cfg.get("fewshot_pool_dir", str(self.project_root / "Traitor_Agent" / "pools"))
        self.pool = FewShotPool(Path(pool_dir))

        self.system_prompt = (
            "You are Traitor, an autonomous Rust transformation agent for compiler fuzzing. "
            "Preserve core semantics, increase trait-system participation, and output only Rust code."
        )

    def _llm(self, prompt: str) -> str:
        return _strip_code_fence(self.connector.query(prompt, system_prompt=self.system_prompt))

    def _log(self, msg: str) -> None:
        if not self.verbose:
            return
        now = datetime.now().strftime("%H:%M:%S")
        print(f"[TraitorAgent {now}] {msg}", flush=True)

    def _repair_if_needed(
        self,
        code: str,
        expected_fail: bool,
        stage_name: str,
        original_code: str,
        intent: str,
    ) -> str:
        current = code
        max_rounds = max(0, self.repair_iters) + 1
        for round_idx in range(max_rounds):
            outcome = compile_code(
                code=current,
                rustc_cmd=self.compile_cmd,
                extra_args=self.compile_extra_args,
                timeout_sec=self.compile_timeout_sec,
            )
            self._log(f"{stage_name} repair round {round_idx + 1}/{max_rounds}: compile_status={outcome.status}")

            if self.abort_on_crash_hang and outcome.status in ("CRASH", "HANG"):
                self._log(f"{stage_name} early stop on {outcome.status} to avoid resource exhaustion")
                return current

            if expected_fail:
                if outcome.status not in ("CRASH", "HANG"):
                    self._log(f"{stage_name} expected-fail seed accepted at round {round_idx + 1}")
                    return current
            else:
                if outcome.status == "SUCCESS":
                    self._log(f"{stage_name} compile SUCCESS at round {round_idx + 1}")
                    return current

            prompt = repair_prompt(
                original_code=_strip_rust_comments(original_code),
                transformed_code=_strip_rust_comments(current),
                compiler_error=outcome.stderr or outcome.stdout,
                stage_name=stage_name,
                intent=intent,
            )
            fixed = self._llm(prompt)
            if fixed:
                current = fixed
                self._log(f"{stage_name} got repaired candidate from LLM")
        return current

    def _select_features(self, code: str) -> List[str]:
        raw = self._llm(feature_select_prompt(_strip_rust_comments(code)))
        allowed = ["GAT", "specialization", "RPIT", "RPITIT", "TAIT", "dynamic_dispatch"]
        decisions = {}

        for line in raw.splitlines():
            item = line.strip(" -\t")
            if not item:
                continue
            lowered = item.lower()
            matched = ""
            for candidate in allowed:
                cand_low = candidate.lower()
                if lowered == cand_low or lowered.startswith(cand_low + ":") or lowered.startswith(cand_low + " "):
                    matched = candidate
                    break
            if not matched:
                for candidate in allowed:
                    if candidate.lower() in lowered:
                        matched = candidate
                        break

            if not matched:
                continue

            has_yes = re.search(r"\b(yes|y|true)\b", lowered) is not None
            has_no = re.search(r"\b(no|n|false)\b", lowered) is not None

            if has_yes and not has_no:
                decisions[matched] = True
            elif has_no and not has_yes:
                decisions[matched] = False

        selected = [feat for feat in allowed if decisions.get(feat, False)]
        return selected

    def _feature_applied(self, code: str, feature: str) -> bool:
        text = code or ""
        if feature == "specialization":
            return (
                "#![feature(specialization)]" in text
                and (
                    re.search(r"\bdefault\s+impl\b", text) is not None
                    or re.search(r"\bdefault\s+fn\b", text) is not None
                    or re.search(r"\bdefault\s+type\b", text) is not None
                )
            )
        if feature == "GAT":
            return re.search(r"type\s+\w+\s*<\s*'\w+\s*>", text) is not None
        if feature == "RPIT":
            return re.search(r"->\s*impl\s+[A-Za-z_][A-Za-z0-9_:<>]*", text) is not None
        if feature == "RPITIT":
            return (
                "#![feature(return_position_impl_trait_in_trait)]" in text
                and re.search(r"trait\s+[^{]+\{[^}]*->\s*impl\s+", text, re.DOTALL) is not None
            )
        if feature == "TAIT":
            return (
                "#![feature(type_alias_impl_trait)]" in text
                and re.search(r"type\s+\w+\s*=\s*impl\s+", text) is not None
            )
        if feature == "dynamic_dispatch":
            return (
                "dyn " in text
                and (
                    re.search(r"\bBox\s*<\s*dyn\s+", text) is not None
                    or re.search(r"\b&\s*dyn\s+", text) is not None
                    or re.search(r"\bArc\s*<\s*dyn\s+", text) is not None
                    or re.search(r"\bRc\s*<\s*dyn\s+", text) is not None
                    or re.search(r"\bdyn\s+[A-Za-z_][A-Za-z0-9_]*(\s*[+][^\n{;]+)?", text) is not None
                )
            )
        return False

    def _detect_applied_feature(self, code: str, candidates: List[str]) -> str:
        for c in candidates:
            if self._feature_applied(code, c):
                return c
        return ""

    def transform(self, program: str) -> TraitorRunResult:
        original = str(program)
        expected_fail = is_expected_fail_seed(original)
        self._log(f"transform start: expected_fail={expected_fail}")

        shots = self.pool.sample_stage1(self.baseline_shots, self.experience_shots)
        self._log(f"stage1 few-shot picked: total={len(shots)} (baseline={self.baseline_shots}, experience={self.experience_shots})")

        stage1_raw = self._llm(stage1_prompt(_strip_rust_comments(original), shots))
        self._log("stage1 generated")
        stage1_intent = (
            "Increase trait participation conservatively: extract suitable standalone/inherent methods into traits, "
            "implement those traits, and use trait-based dispatch without changing original semantics."
        )
        stage1 = self._repair_if_needed(
            stage1_raw or original,
            expected_fail=expected_fail,
            stage_name="Stage-I",
            original_code=original,
            intent=stage1_intent,
        )
        stage1_status = compile_code(
            code=stage1,
            rustc_cmd=self.compile_cmd,
            extra_args=self.compile_extra_args,
            timeout_sec=self.compile_timeout_sec,
        ).status
        self._log(f"stage1 final compile status={stage1_status}")

        tsa_orig_details = self.tsa_meter.measure_with_details(original)
        tsa_stage1_details = self.tsa_meter.measure_with_details(stage1)
        tsa_orig = int(tsa_orig_details.get("score", 0))
        tsa_stage1 = int(tsa_stage1_details.get("score", 0))
        delta1 = tsa_stage1 - tsa_orig
        stage1_accepted_by_tsa = delta1 > 0
        stage1_eligible_for_pool = stage1_accepted_by_tsa and stage1_status == "SUCCESS"
        self._log(
            f"stage1 tsa: orig={tsa_orig}, stage1={tsa_stage1}, delta={delta1}, "
            f"accepted_by_tsa={stage1_accepted_by_tsa}, eligible_for_pool={stage1_eligible_for_pool}"
        )

        if stage1_status != "SUCCESS":
            self._log("stage1 compile failed -> skip stage2")
            return TraitorRunResult(
                stage1_output_code=stage1,
                output_code=stage1,
                stage="stage1",
                tsa_original=tsa_orig,
                tsa_output=tsa_stage1,
                delta_tsa=delta1,
                accepted_by_tsa=stage1_accepted_by_tsa,
                selected_feature="",
                applied_feature="",
                candidate_features=[],
                expected_fail_seed=expected_fail,
                tsa_method=str(tsa_stage1_details.get("method", "unknown")),
                tsa_compiler_mode=int(self.agent_cfg.get("tsa_compiler_mode", 1)),
                stage1_tsa=tsa_stage1,
                stage2_tsa=tsa_stage1,
                stage1_accepted_by_tsa=stage1_accepted_by_tsa,
                stage2_accepted_by_tsa=False,
                feature_applied=False,
                stage1_compile_status=stage1_status,
                stage2_compile_status="SKIPPED",
                stage2_attempted=False,
                final_compile_status=stage1_status,
                eligible_for_seed=False,
                stage1_eligible_for_pool=stage1_eligible_for_pool,
                stage2_eligible_for_pool=False,
            )

        features = self._select_features(stage1)
        if not features:
            self._log("stage2 feature candidates empty from LLM -> skip stage2")
            return TraitorRunResult(
                stage1_output_code=stage1,
                output_code=stage1,
                stage="stage1",
                tsa_original=tsa_orig,
                tsa_output=tsa_stage1,
                delta_tsa=delta1,
                accepted_by_tsa=stage1_accepted_by_tsa,
                selected_feature="",
                applied_feature="",
                candidate_features=[],
                expected_fail_seed=expected_fail,
                tsa_method=str(tsa_stage1_details.get("method", "unknown")),
                tsa_compiler_mode=int(self.agent_cfg.get("tsa_compiler_mode", 1)),
                stage1_tsa=tsa_stage1,
                stage2_tsa=tsa_stage1,
                stage1_accepted_by_tsa=stage1_accepted_by_tsa,
                stage2_accepted_by_tsa=False,
                feature_applied=False,
                stage1_compile_status=stage1_status,
                stage2_compile_status="SKIPPED",
                stage2_attempted=False,
                final_compile_status=stage1_status,
                eligible_for_seed=False,
                stage1_eligible_for_pool=stage1_eligible_for_pool,
                stage2_eligible_for_pool=False,
            )
        selected_feature = random.choice(features)
        self._log(f"stage2 feature candidates={features}, selected={selected_feature}")

        shots2 = self.pool.sample_stage2(selected_feature, self.baseline_shots, self.experience_shots)
        self._log(
            f"stage2 few-shot picked: total={len(shots2)} "
            f"(generic={self.baseline_shots}, feature={self.experience_shots}, feature={selected_feature})"
        )
        stage2_raw = self._llm(stage2_prompt(_strip_rust_comments(stage1), selected_feature, shots2))
        self._log("stage2 generated")
        stage2_intent = (
            f"Introduce feature {selected_feature} explicitly while preserving Stage-I and original semantics."
        )
        stage2 = self._repair_if_needed(
            stage2_raw or stage1,
            expected_fail=expected_fail,
            stage_name="Stage-II",
            original_code=stage1,
            intent=stage2_intent,
        )

        applied_feature = self._detect_applied_feature(stage2, [selected_feature, *[f for f in features if f != selected_feature]])
        stage2_status = compile_code(
            code=stage2,
            rustc_cmd=self.compile_cmd,
            extra_args=self.compile_extra_args,
            timeout_sec=self.compile_timeout_sec,
        ).status
        self._log(f"stage2 final compile status={stage2_status}, applied_feature={applied_feature or '(none)'}")

        # Stage-II gating rule: compile SUCCESS is sufficient for seed admission.
        # Keep TSA output fields for compatibility with existing summary schema.
        tsa_stage2 = tsa_stage1
        delta2 = delta1
        stage2_accepted_by_tsa = stage1_accepted_by_tsa
        stage2_eligible_for_pool = (stage2_status == "SUCCESS")
        self._log(
            f"transform end: eligible_for_seed={stage2_status == 'SUCCESS'}, "
            f"stage1_pool={stage1_eligible_for_pool}, stage2_pool={stage2_eligible_for_pool}"
        )

        return TraitorRunResult(
            stage1_output_code=stage1,
            output_code=stage2,
            stage="stage2",
            tsa_original=tsa_orig,
            tsa_output=tsa_stage2,
            delta_tsa=delta2,
            accepted_by_tsa=stage2_accepted_by_tsa,
            selected_feature=selected_feature,
            applied_feature=applied_feature,
            candidate_features=features,
            expected_fail_seed=expected_fail,
            tsa_method=str(tsa_stage1_details.get("method", "unknown")),
            tsa_compiler_mode=int(self.agent_cfg.get("tsa_compiler_mode", 1)),
            stage1_tsa=tsa_stage1,
            stage2_tsa=tsa_stage2,
            stage1_accepted_by_tsa=stage1_accepted_by_tsa,
            stage2_accepted_by_tsa=stage2_accepted_by_tsa,
            feature_applied=bool(applied_feature),
            stage1_compile_status=stage1_status,
            stage2_compile_status=stage2_status,
            stage2_attempted=True,
            final_compile_status=stage2_status,
            eligible_for_seed=(stage2_status == "SUCCESS"),
            stage1_eligible_for_pool=stage1_eligible_for_pool,
            stage2_eligible_for_pool=stage2_eligible_for_pool,
        )


def load_full_config(config_path: Path) -> Dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)
