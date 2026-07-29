"""Pipeline assembly: the three switchable configurations (FR7).

    Configuration.NO_VERIFIER   Extractor -> Analyst -> Writer
    Configuration.SELF_CHECK    Extractor -> Analyst -> SelfCheck -> Writer
    Configuration.DEMINH        Extractor -> Analyst -> Deterministic -> Writer

Everything except the verification node is held identical. That is the whole
point of the design: the only variable that moves between arms is the checker.
Resist the urge to "improve" the DeMiNH arm's prompts — the moment the arms
differ in more than one respect, the experiment stops isolating independence and
your central claim becomes unsupportable.

LangGraph is used because the control flow is explicit and inspectable, and
because a verification node can be inserted at a named point without disturbing
the rest of the graph. `run_sequential` gives identical behaviour without the
dependency, which is convenient for unit tests and for debugging on a machine
that cannot load the model.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, TypedDict

from .agents import Analyst, Extractor, Writer, claim_from_derivation
from .llm import LLMBackend
from .schemas import PipelineRecord
from .verification.orchestrator import RepairPolicy, Verifier, VerifierConfig
from .verification.recompute import ExpressionError, safe_eval


class Configuration(str, Enum):
    NO_VERIFIER = "no_verifier"
    SELF_CHECK = "self_check"
    DEMINH = "deminh"


def verifier_config_for(configuration: Configuration) -> Optional[VerifierConfig]:
    if configuration is Configuration.NO_VERIFIER:
        return None
    if configuration is Configuration.SELF_CHECK:
        return VerifierConfig(
            use_recompute=False,
            use_provenance=False,
            use_identities=False,
            use_self_check=True,
            repair_policy=RepairPolicy.ANY_PROPOSAL,
        )
    return VerifierConfig(
        use_recompute=True,
        use_provenance=True,
        use_identities=True,
        use_self_check=False,
        repair_policy=RepairPolicy.RECOMPUTE_ONLY,
    )


class GraphState(TypedDict, total=False):
    record: PipelineRecord
    configuration: str


class Pipeline:
    """Holds the agents and the verifier for one configuration."""

    def __init__(self, backend: LLMBackend, configuration: Configuration,
                 identity_set: Optional[list] = None):
        self.backend = backend
        self.configuration = configuration
        self.extractor = Extractor(backend)
        self.analyst = Analyst(backend)
        self.writer = Writer(backend)
        cfg = verifier_config_for(configuration)
        self.verifier = (
            Verifier(cfg, backend=backend, identity_set=identity_set) if cfg else None
        )

    # -- nodes -------------------------------------------------------------

    def node_extract(self, state: GraphState) -> GraphState:
        record = state["record"]
        record.figures = self.extractor.run(record)
        return {"record": record}

    def node_analyse(self, state: GraphState) -> GraphState:
        record = state["record"]
        derivation = self.analyst.run(record)
        if derivation is None:
            record.claims = []
            return {"record": record}

        # The claim's value is the Analyst's *estimate*. Configuration 1 ships
        # this estimate untouched — that is precisely what makes it the baseline.
        record.claims = [claim_from_derivation(derivation, derivation.claimed_result)]
        record.meta["analyst_estimate"] = derivation.claimed_result
        return {"record": record}

    def node_verify(self, state: GraphState) -> GraphState:
        record = state["record"]
        if self.verifier is not None:
            record.report = self.verifier.run(record)
        return {"record": record}

    def node_write(self, state: GraphState) -> GraphState:
        record = state["record"]
        value = record.claims[0].value if record.claims else None
        record.final_answer = value
        record.answer_text = self.writer.run(record, value)
        return {"record": record}

    # -- execution ---------------------------------------------------------

    def run_sequential(self, record: PipelineRecord) -> PipelineRecord:
        """Dependency-free execution. Behaviourally identical to the graph."""
        state: GraphState = {"record": record, "configuration": self.configuration.value}
        state.update(self.node_extract(state))
        state.update(self.node_analyse(state))
        if self.verifier is not None:
            state.update(self.node_verify(state))
        state.update(self.node_write(state))
        return state["record"]

    def build_graph(self) -> Any:
        """Compile the LangGraph representation."""
        from langgraph.graph import END, START, StateGraph

        graph = StateGraph(GraphState)
        graph.add_node("extract", self.node_extract)
        graph.add_node("analyse", self.node_analyse)
        graph.add_node("write", self.node_write)

        graph.add_edge(START, "extract")
        graph.add_edge("extract", "analyse")

        if self.verifier is not None:
            graph.add_node("verify", self.node_verify)
            graph.add_edge("analyse", "verify")
            graph.add_edge("verify", "write")
        else:
            graph.add_edge("analyse", "write")

        graph.add_edge("write", END)
        return graph.compile()

    def run(self, record: PipelineRecord, use_langgraph: bool = True) -> PipelineRecord:
        if not use_langgraph:
            return self.run_sequential(record)
        compiled = self.build_graph()
        result = compiled.invoke({"record": record,
                                  "configuration": self.configuration.value})
        return result["record"]
