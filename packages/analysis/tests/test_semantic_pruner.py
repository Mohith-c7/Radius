from unittest.mock import MagicMock, patch

import pytest
from radius_analysis.ai import pruner as _pruner_module
from radius_analysis.ai.pruner import SemanticPruner

# The google-genai SDK is an optional extra (installed via the dev extra in CI).
requires_genai = pytest.mark.skipif(
    _pruner_module.genai is None, reason="google-genai SDK not installed"
)

# ==========================================
# Modern google-genai SDK tests (_USE_GENAI=True)
# ==========================================


@requires_genai
@patch("radius_analysis.ai.pruner._USE_GENAI", True)
@patch("radius_analysis.ai.pruner.genai.Client")
def test_semantic_pruner_impacted(mock_client_class):
    mock_client = mock_client_class.return_value
    mock_response = MagicMock()
    mock_response.text = (
        '{"impacted": true, "reason": "Throws an unhandled exception."}'
    )
    mock_client.models.generate_content.return_value = mock_response

    pruner = SemanticPruner("dummy_key")
    result = pruner.evaluate_impact(
        "def caller(): return callee()", "- return 1\n+ raise ValueError()"
    )

    assert result is True
    mock_client_class.assert_called_once_with(api_key="dummy_key")
    mock_client.models.generate_content.assert_called_once()
    call_kwargs = mock_client.models.generate_content.call_args.kwargs
    assert call_kwargs["model"] == "gemini-2.0-flash"
    assert call_kwargs["config"]["response_mime_type"] == "application/json"
    from radius_analysis.ai.pruner import PrunerDecision
    assert call_kwargs["config"]["response_schema"] == PrunerDecision


@requires_genai
@patch("radius_analysis.ai.pruner._USE_GENAI", True)
@patch("radius_analysis.ai.pruner.genai.Client")
def test_semantic_pruner_benign(mock_client_class):
    mock_client = mock_client_class.return_value
    mock_response = MagicMock()
    mock_response.text = (
        '{"impacted": false, "reason": "Added a benign log statement."}'
    )
    mock_client.models.generate_content.return_value = mock_response

    pruner = SemanticPruner("dummy_key")
    result = pruner.evaluate_impact(
        "def caller(): return callee()", "+ print('debug log')"
    )

    assert result is False
    mock_client_class.assert_called_once_with(api_key="dummy_key")
    mock_client.models.generate_content.assert_called_once()


@requires_genai
@patch("radius_analysis.ai.pruner._USE_GENAI", True)
@patch("radius_analysis.ai.pruner.genai.Client")
def test_semantic_pruner_fallback_on_error(mock_client_class):
    mock_client = mock_client_class.return_value
    mock_client.models.generate_content.side_effect = Exception("API Timeout")

    pruner = SemanticPruner("dummy_key")
    result = pruner.evaluate_impact("def caller(): pass", "diff")

    # Must fallback to True for safety (do not prune if unsure)
    assert result is True


@requires_genai
@patch("radius_analysis.ai.pruner._USE_GENAI", True)
@patch("radius_analysis.ai.pruner.genai.Client")
def test_semantic_pruner_fallback_on_invalid_json(mock_client_class):
    mock_client = mock_client_class.return_value
    mock_response = MagicMock()
    mock_response.text = "Not JSON output"
    mock_client.models.generate_content.return_value = mock_response

    pruner = SemanticPruner("dummy_key")
    result = pruner.evaluate_impact("def caller(): pass", "diff")

    # Must fallback to True on invalid JSON
    assert result is True


# ==========================================
# Legacy google-generativeai SDK tests (_USE_GENAI=False)
# ==========================================


@pytest.mark.filterwarnings("ignore::FutureWarning")
def test_legacy_semantic_pruner_impacted():
    mock_legacy_genai = MagicMock()
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = (
        '{"impacted": true, "reason": "Throws an unhandled exception."}'
    )
    mock_model.generate_content.return_value = mock_response
    mock_legacy_genai.GenerativeModel.return_value = mock_model

    with (
        patch("radius_analysis.ai.pruner._USE_GENAI", False),
        patch("radius_analysis.ai.pruner.genai", mock_legacy_genai),
    ):
        pruner = SemanticPruner("dummy_key")
        result = pruner.evaluate_impact(
            "def caller(): return callee()", "- return 1\n+ raise ValueError()"
        )

        assert result is True
        mock_legacy_genai.configure.assert_called_once_with(api_key="dummy_key")
        mock_legacy_genai.GenerativeModel.assert_called_once_with("gemini-1.5-flash")
        mock_model.generate_content.assert_called_once()


@pytest.mark.filterwarnings("ignore::FutureWarning")
def test_legacy_semantic_pruner_benign():
    mock_legacy_genai = MagicMock()
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = (
        '{"impacted": false, "reason": "Added a benign log statement."}'
    )
    mock_model.generate_content.return_value = mock_response
    mock_legacy_genai.GenerativeModel.return_value = mock_model

    with (
        patch("radius_analysis.ai.pruner._USE_GENAI", False),
        patch("radius_analysis.ai.pruner.genai", mock_legacy_genai),
    ):
        pruner = SemanticPruner("dummy_key")
        result = pruner.evaluate_impact(
            "def caller(): return callee()", "+ print('debug log')"
        )

        assert result is False
        mock_legacy_genai.configure.assert_called_once_with(api_key="dummy_key")
        mock_legacy_genai.GenerativeModel.assert_called_once_with("gemini-1.5-flash")
        mock_model.generate_content.assert_called_once()


@pytest.mark.filterwarnings("ignore::FutureWarning")
def test_legacy_semantic_pruner_fallback_on_error():
    mock_legacy_genai = MagicMock()
    mock_model = MagicMock()
    mock_model.generate_content.side_effect = Exception("API Timeout")
    mock_legacy_genai.GenerativeModel.return_value = mock_model

    with (
        patch("radius_analysis.ai.pruner._USE_GENAI", False),
        patch("radius_analysis.ai.pruner.genai", mock_legacy_genai),
    ):
        pruner = SemanticPruner("dummy_key")
        result = pruner.evaluate_impact("def caller(): pass", "diff")

        assert result is True


@pytest.mark.filterwarnings("ignore::FutureWarning")
def test_legacy_semantic_pruner_fallback_on_invalid_json():
    mock_legacy_genai = MagicMock()
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "invalid json payload"
    mock_model.generate_content.return_value = mock_response
    mock_legacy_genai.GenerativeModel.return_value = mock_model

    with (
        patch("radius_analysis.ai.pruner._USE_GENAI", False),
        patch("radius_analysis.ai.pruner.genai", mock_legacy_genai),
    ):
        pruner = SemanticPruner("dummy_key")
        result = pruner.evaluate_impact("def caller(): pass", "diff")

        assert result is True


def test_gemini_key_ignored_without_explicit_flag() -> None:
    from radius_analysis.ai.pruner import gemini_api_key_from_env

    assert gemini_api_key_from_env({"GEMINI_API_KEY": "k"}) == ""
    assert (
        gemini_api_key_from_env(
            {"GEMINI_API_KEY": "k", "RADIUS_FEATURE_GEMINI_PRUNER": "false"}
        )
        == ""
    )


def test_gemini_key_used_when_flag_is_on() -> None:
    from radius_analysis.ai.pruner import gemini_api_key_from_env

    env = {"GEMINI_API_KEY": " k ", "RADIUS_FEATURE_GEMINI_PRUNER": "TRUE"}
    assert gemini_api_key_from_env(env) == "k"
    assert gemini_api_key_from_env({"RADIUS_FEATURE_GEMINI_PRUNER": "1"}) == ""
