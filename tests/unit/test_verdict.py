from tradingagent.core.types import RuleResult, Verdict


def _r(rule_id, passed, authority="ENFORCE"):
    return RuleResult(rule_id, passed, "OK" if passed else "FAIL", authority=authority)


def test_all_pass_approves():
    assert Verdict((_r("G01", True), _r("G16", True, "SHADOW"))).approved


def test_enforce_failure_rejects():
    v = Verdict((_r("G01", True), _r("G09", False)))
    assert not v.approved
    assert [r.rule_id for r in v.blocking_failures] == ["G09"]


def test_shadow_failure_is_logged_but_never_blocks():
    v = Verdict((_r("G01", True), _r("G16", False, "SHADOW"), _r("G17", False, "SHADOW")))
    assert v.approved
    assert v.blocking_failures == ()
    assert [r.rule_id for r in v.shadow_failures] == ["G16", "G17"]


def test_default_authority_is_enforce():
    assert RuleResult("G02", False, "HALTED").blocks
