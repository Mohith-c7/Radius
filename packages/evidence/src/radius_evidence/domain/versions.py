"""Algorithm version constants stamped on every item, edge and result."""

#: Version of the frozen data contracts (model/inputs). 2: AssertionFact strength flags,
#: Reason.rule_id, StageAInput.added_test_ids / agent_signal_by_test, 4th freshness reason.
#: 3: StageAInput.repo_config (policy/waivers captured at the base ref), VerdictV2.policy /
#: waivers / tamper_waived, justification.policy / waivers, rules P1/P2 (only with a policy).
#: 4: provenance tags (CriterionInput.provenance / hints_provenance, CriterionTestEdgeInput.provenance),
#: Flag.AUTHOR_SUPPLIED_HINT, LinkMapping.author_hint_cap, payload honesty fields.
#: All additions are optional with defaults, so contract-1 and -2 payloads still load.
CONTRACT_VERSION = "verdict-v2-contract-4"

ALGO_VERSION = "verdict-v2-alpha-1"
PROFILE_ALPHA_STATIC = "alpha-static"

EVIDENCE_QUALITY_VERSION = "evq-static-1"
SUPPORT_VERSION = "support-noisyor-1"
IEG_VERSION = "ieg-1"
ASSERTIONS_VERSION = "test-assertions-v1"
RELEVANCE_VERSION = "test-relevance-1"
FRESHNESS_VERSION = "fresh-1"
INDEPENDENCE_VERSION = "indep-lite-1"
SYMBOL_CHANGES_VERSION = "symbol-changes-v1"
CRITERION_SYMBOL_LINKS_VERSION = "criterion-symbol-links-v1"
SYMBOL_TEST_LINKS_VERSION = "link-combine-v1"
TAMPER_VERSION = "tamper-rules-v1"

JUSTIFICATION_SCHEMA = "verdict-v2-justification-1"
BUNDLE_SCHEMA = "verdict-v2-bundle-1"

#: Component versions copied into ``justification.versions`` (design 3.9).
DEFAULT_COMPONENT_VERSIONS: dict[str, str] = {
    "verdict": ALGO_VERSION,
    "evidence_quality": EVIDENCE_QUALITY_VERSION,
    "support": SUPPORT_VERSION,
    "ieg": IEG_VERSION,
    "assertions": ASSERTIONS_VERSION,
    "relevance": RELEVANCE_VERSION,
    "freshness": FRESHNESS_VERSION,
    "independence": INDEPENDENCE_VERSION,
    "symbol_changes": SYMBOL_CHANGES_VERSION,
    "criterion_symbol_links": CRITERION_SYMBOL_LINKS_VERSION,
    "symbol_test_links": SYMBOL_TEST_LINKS_VERSION,
    "tamper": TAMPER_VERSION,
}
