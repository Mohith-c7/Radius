"""Lexical (BM25) and identifier/phrase linkers with hand-crafted cases."""

from __future__ import annotations

import pytest
from linking_helpers import by_symbol, crit, sym
from radius_linking.domain import LinkContext
from radius_linking.infrastructure.linkers import (
    IdentifierLinker,
    LexicalConfig,
    LexicalLinker,
    extract_anchors,
)

CTX = LinkContext()

DISCOUNT = sym(
    "src/pricing.py",
    "apply_discount",
    signature="(price: float, percent: float) -> float",
    docstring="Reduce price by percent, rounded to 2 decimals.",
    identifiers=("percent", "price", "round", "ValueError"),
    literals=("percent must be between 0 and 100", "2", "100"),
)
EMAIL = sym(
    "src/emails.py",
    "normalize_email",
    docstring="Lowercase and strip an email address.",
    identifiers=("strip", "lower", "address"),
)
CART = sym("src/cart.py", "Cart.checkout", identifiers=("total", "items"))


def lex(text, symbols, **kw):
    return by_symbol(LexicalLinker().link([crit(text, **kw)], symbols, CTX))


# ------------------------------------------------------------------ lexical


def test_lexical_ranks_the_matching_symbol_first():
    got = lex("apply a discount percent to the price", [DISCOUNT, EMAIL, CART])
    assert got[DISCOUNT.symbol_id].score > 0
    assert EMAIL.symbol_id not in got and CART.symbol_id not in got


def test_lexical_uses_docstring_and_identifiers():
    got = lex("lowercase and strip the address", [DISCOUNT, EMAIL])
    assert set(got) == {EMAIL.symbol_id}


def test_lexical_splits_camel_and_snake_in_names():
    s = sym("src/api.py", "getUserProfile")
    got = lex("fetch the user profile", [s, CART])
    assert set(got) == {s.symbol_id}


def test_lexical_score_is_bounded_by_cap():
    got = lex("apply discount percent price round decimals", [DISCOUNT])
    assert 0 < got[DISCOUNT.symbol_id].score <= 0.9


def test_lexical_more_matches_means_higher_score():
    one = lex("discount", [DISCOUNT, EMAIL])[DISCOUNT.symbol_id].score
    many = lex("apply discount percent", [DISCOUNT, EMAIL])[DISCOUNT.symbol_id].score
    assert many > one


def test_lexical_name_field_outweighs_comment_mentions():
    named = sym("src/a.py", "refund_order")
    commented = sym("src/b.py", "helper", comments=("refund order maybe later",))
    got = lex("refund order", [named, commented])
    assert got[named.symbol_id].score > got[commented.symbol_id].score


def test_lexical_rationale_terms_count_less_than_text_terms():
    s1 = sym("src/a.py", "alpha_beta")
    s2 = sym("src/b.py", "gamma_delta")
    with_rationale = lex("alpha beta", [s1, s2], rationale="gamma delta")
    assert with_rationale[s1.symbol_id].score > with_rationale[s2.symbol_id].score


def test_lexical_reasons_list_matched_terms():
    got = lex("apply discount", [DISCOUNT, EMAIL])[DISCOUNT.symbol_id]
    kinds = [e.kind for e in got.evidence]
    assert "bm25_term" in kinds and "bm25_summary" in kinds
    assert any("discount" in e.detail for e in got.evidence)


def test_lexical_empty_or_stopword_only_criterion_is_silent():
    assert lex("", [DISCOUNT]) == {}
    assert lex("the of and to a", [DISCOUNT]) == {}


def test_lexical_no_symbols_and_unknown_terms():
    assert LexicalLinker().link([crit("discount")], [], CTX) == []
    assert lex("zzzz qqqq", [DISCOUNT]) == {}


def test_lexical_unicode_terms_match():
    s = sym("src/preis.py", "berechne_rabatt", docstring="Berechnet den Rabatt")
    assert lex("Rabatt berechnen", [s])[s.symbol_id].score > 0
    ja = sym("src/ja.py", "割引_計算")
    assert lex("割引", [ja])[ja.symbol_id].score > 0


def test_lexical_path_tokens_help_but_generic_dirs_do_not():
    s = sym("src/billing/invoices.py", "f")
    assert lex("invoices", [s])[s.symbol_id].score > 0
    assert lex("src", [s]) == {}


def test_lexical_config_cap_is_respected():
    linker = LexicalLinker(LexicalConfig(cap=0.5))
    got = by_symbol(linker.link([crit("apply discount percent")], [DISCOUNT], CTX))
    assert got[DISCOUNT.symbol_id].score <= 0.5


def test_lexical_is_independent_of_symbol_order():
    a = lex("discount percent email", [DISCOUNT, EMAIL, CART])
    b = lex("discount percent email", [CART, EMAIL, DISCOUNT])
    assert {k: v.score for k, v in a.items()} == {k: v.score for k, v in b.items()}


# ------------------------------------------------------------------ anchors


def kinds(text):
    return {(a.kind, a.text) for a in extract_anchors(text)}


def test_anchor_snake_camel_and_call_names():
    assert ("symbol_name", "apply_discount") in kinds("Call apply_discount first")
    assert ("symbol_name", "applyDiscount") in kinds("Call applyDiscount first")
    assert ("symbol_name", "checkout") in kinds("`checkout()` is invoked")


def test_anchor_endpoint_and_params():
    assert ("endpoint", "/api/v1/users/{id}") in kinds(
        "GET /api/v1/users/{id} returns 404"
    )
    assert ("endpoint", "/health") in kinds("expose `/health`")


def test_anchor_status_requires_context_else_number():
    assert ("status", "404") in kinds("responds with status 404 when missing")
    assert ("number", "404") not in kinds("responds with status 404")
    assert ("number", "100") in kinds("up to 100 items")


def test_anchor_quoted_error_strings_and_flags_and_keys():
    ks = kinds(
        'raise "percent must be between 0 and 100" and accept --dry-run, read MAX_RETRIES'
    )
    assert ("error_string", "percent must be between 0 and 100") in ks
    assert ("flag", "--dry-run") in ks
    assert ("config_key", "MAX_RETRIES") in ks


def test_anchor_dotted_config_key_but_not_file_names_or_abbreviations():
    ks = kinds("set db.pool.size and edit config.yaml, i.e. e.g. things")
    assert ("config_key", "db.pool.size") in ks
    assert all(t != "config.yaml" for _, t in ks)
    assert all(t not in {"i.e", "e.g"} for _, t in ks)


def test_anchor_exceptions():
    assert ("exception", "ValueError") in kinds("raises ValueError for bad input")


def test_anchors_are_deduplicated_and_bounded():
    text = (
        " ".join(f"name_{i}_x" for i in range(100)) + " apply_discount apply_discount"
    )
    anchors = extract_anchors(text)
    assert len(anchors) <= 40
    assert len({(a.kind, a.text.casefold()) for a in anchors}) == len(anchors)


def test_anchors_of_plain_prose_are_empty():
    assert extract_anchors("make the page faster and nicer") == []


# ------------------------------------------------------------------ identifier matching


def ident(text, symbols):
    return by_symbol(IdentifierLinker().link([crit(text)], symbols, CTX))


def test_exact_symbol_name_in_any_naming_style():
    got = ident("apply_discount must round", [DISCOUNT, EMAIL])
    assert got[DISCOUNT.symbol_id].score == pytest.approx(0.9)
    assert EMAIL.symbol_id not in got
    got2 = ident("applyDiscount() must round", [DISCOUNT])
    assert got2[DISCOUNT.symbol_id].evidence[0].kind == "symbol_name"


def test_fuzzy_name_match_scores_below_exact():
    got = ident("normalise_email trims input", [EMAIL])
    exact = ident("normalize_email trims input", [EMAIL])
    assert 0 < got[EMAIL.symbol_id].score < exact[EMAIL.symbol_id].score


def test_qualified_name_tokens_contained():
    got = ident("`Cart.checkout_total` is called", [CART])
    assert got[CART.symbol_id].score > 0


def test_identifier_used_in_body_is_weaker_than_name():
    body = sym("src/x.py", "other", identifiers=("apply_discount",))
    got = ident("apply_discount", [DISCOUNT, body])
    assert got[DISCOUNT.symbol_id].score > got[body.symbol_id].score > 0


def test_error_string_exact_and_substring_and_fuzzy():
    msg = "percent must be between 0 and 100"
    exact = ident(f'raises ValueError("{msg}")', [DISCOUNT])
    assert exact[DISCOUNT.symbol_id].score > 0.8
    sub = ident('shows "must be between 0 and 100" error', [DISCOUNT])
    assert sub[DISCOUNT.symbol_id].score > 0
    fuzzy = ident('shows "percent has to be between 0 and 100"', [DISCOUNT])
    assert 0 < fuzzy[DISCOUNT.symbol_id].score < exact[DISCOUNT.symbol_id].score


def test_endpoint_matches_route_decorator_with_param_styles():
    route = sym(
        "src/api.py", "get_user", decorators=('app.get("/api/v1/users/{user_id}")',)
    )
    flask = sym(
        "src/api2.py",
        "get_user2",
        decorators=("@app.route('/api/v1/users/<int:uid>')",),
    )
    got = ident("GET /api/v1/users/{id} returns the user", [route, flask])
    # both routes match once <int:uid> / {user_id} normalise to {}; rarity halves-ish
    assert got[route.symbol_id].score == pytest.approx(0.9 / 1.5)
    assert got[flask.symbol_id].score == pytest.approx(0.9 / 1.5)
    alone = ident("GET /api/v1/users/{id} returns the user", [route])
    assert alone[route.symbol_id].score == pytest.approx(0.9)


def test_endpoint_partial_overlap_scores_lower():
    prefixed = sym("src/api.py", "h", literals=("/internal/api/v1/users",))
    got = ident("`/api/v1/users` lists users", [prefixed])
    assert 0 < got[prefixed.symbol_id].score < 0.9


def test_http_status_matches_literal_and_constant_names():
    lit = sym("src/a.py", "a", literals=("404",))
    const = sym("src/b.py", "b", identifiers=("HTTP_404_NOT_FOUND",))
    got = ident("responds with status 404", [lit, const])
    assert got[lit.symbol_id].score > got[const.symbol_id].score > 0


def test_cli_flag_in_literal_and_as_argument_name():
    a = sym("src/cli.py", "main", literals=("--dry-run", "store_true"))
    b = sym("src/other.py", "run", identifiers=("dry_run",))
    got = ident("supports the --dry-run flag", [a, b])
    assert got[a.symbol_id].score > got[b.symbol_id].score > 0


def test_config_key_via_literal_identifier_and_name():
    a = sym("src/c.py", "load", literals=("MAX_RETRIES",))
    b = sym("src/d.py", "MAX_RETRIES", kind="variable")
    got = ident("MAX_RETRIES defaults to 3", [a, b])
    assert a.symbol_id in got and b.symbol_id in got


def test_exception_anchor_is_weighted_down_when_common():
    rare = sym("src/a.py", "a", identifiers=("TimeoutError",))
    many = [sym(f"src/m{i}.py", f"m{i}", identifiers=("ValueError",)) for i in range(6)]
    got_common = ident("raises ValueError", many)
    got_rare = ident("raises TimeoutError", [rare, *many])
    assert got_rare[rare.symbol_id].score > got_common[many[0].symbol_id].score


def test_numeric_literal_is_a_weak_signal():
    got = ident("limit of 100 items", [DISCOUNT])
    assert 0 < got[DISCOUNT.symbol_id].score <= 0.25


def test_identifier_score_capped_and_reasons_explain_anchor():
    msg = "percent must be between 0 and 100"
    got = ident(f'apply_discount raises ValueError "{msg}" for 100', [DISCOUNT])[
        DISCOUNT.symbol_id
    ]
    assert got.score <= 0.92
    assert len(got.evidence) >= 3
    assert all("anchor" in e.detail for e in got.evidence)


def test_identifier_silent_without_anchors_or_matches():
    assert ident("make it faster", [DISCOUNT]) == {}
    assert ident("calls unknown_function_name now", [DISCOUNT, EMAIL]) == {}


def test_identifier_is_deterministic():
    one = IdentifierLinker().link(
        [crit("apply_discount and normalize_email")], [DISCOUNT, EMAIL], CTX
    )
    two = IdentifierLinker().link(
        [crit("apply_discount and normalize_email")], [EMAIL, DISCOUNT], CTX
    )
    assert sorted((x.symbol_id, x.score) for x in one) == sorted(
        (x.symbol_id, x.score) for x in two
    )


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("`/health`", "endpoint", "/health"),
        ("`--dry-run`", "flag", "--dry-run"),
        ("`ValueError`", "exception", "ValueError"),
        ("`503`", "status", "503"),
        ("`not found here`", "error_string", "not found here"),
        ("`MAX_RETRIES`", "config_key", "MAX_RETRIES"),
        ("`db.pool.size`", "config_key", "db.pool.size"),
        ("`compute()`", "symbol_name", "compute"),
    ],
)
def test_backticked_anchor_classification(text, kind, value):
    assert (kind, value) in kinds(text)


def test_backticked_junk_yields_no_anchor():
    assert extract_anchors("`` `7` `x`") == [] or all(
        a.kind != "symbol_name" for a in extract_anchors("`` `7`")
    )


def test_name_match_single_token_partial_and_literal_fallbacks():
    part = sym("src/a.py", "Invoice.render_total")
    assert ident("`render`", [part])[part.symbol_id].score > 0
    lit = sym("src/b.py", "other", literals=("render",))
    assert ident("`render`", [lit])[lit.symbol_id].score > 0


def test_config_key_last_segment_and_exception_defined_symbol():
    k = sym("src/a.py", "load", identifiers=("size",))
    assert ident("set db.pool.size", [k])[k.symbol_id].score > 0
    e = sym("src/e.py", "TimeoutError", kind="class")
    assert ident("raises TimeoutError", [e])[e.symbol_id].score > 0
