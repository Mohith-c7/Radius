import pytest
from unittest.mock import MagicMock, patch
from radius_analysis.ai.pruner import SemanticPruner

@patch('radius_analysis.ai.pruner.genai.GenerativeModel')
def test_semantic_pruner_impacted(mock_model_class):
    # Setup Mock
    mock_instance = mock_model_class.return_value
    mock_response = MagicMock()
    mock_response.text = '{"impacted": true, "reason": "Throws an unhandled exception."}'
    mock_instance.generate_content.return_value = mock_response
    
    pruner = SemanticPruner("dummy_key")
    result = pruner.evaluate_impact("def caller(): return callee()", "- return 1\n+ raise ValueError()")
    
    assert result is True

@patch('radius_analysis.ai.pruner.genai.GenerativeModel')
def test_semantic_pruner_benign(mock_model_class):
    # Setup Mock
    mock_instance = mock_model_class.return_value
    mock_response = MagicMock()
    mock_response.text = '{"impacted": false, "reason": "Added a benign log statement."}'
    mock_instance.generate_content.return_value = mock_response
    
    pruner = SemanticPruner("dummy_key")
    result = pruner.evaluate_impact("def caller(): return callee()", "+ print('debug log')")
    
    assert result is False

@patch('radius_analysis.ai.pruner.genai.GenerativeModel')
def test_semantic_pruner_fallback_on_error(mock_model_class):
    # Setup Mock to simulate a network error
    mock_instance = mock_model_class.return_value
    mock_instance.generate_content.side_effect = Exception("API Timeout")
    
    pruner = SemanticPruner("dummy_key")
    result = pruner.evaluate_impact("def caller(): pass", "diff")
    
    # Must fallback to True for safety (do not prune if unsure)
    assert result is True
