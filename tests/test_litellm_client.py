from unittest.mock import MagicMock, patch
import pytest
from src.integrations.litellm_client import LiteLLMClient

@patch("src.integrations.litellm_client.Router")
def test_litellm_client_init(mock_router: MagicMock) -> None:
    """Tests that the client initializes the LiteLLM Router with configs."""
    client = LiteLLMClient()
    assert mock_router.called
    assert client.total_cost_usd == 0.0
    assert client.total_prompt_tokens == 0
    assert client.total_completion_tokens == 0

@patch("src.integrations.litellm_client.Router")
@patch("litellm.completion_cost")
def test_litellm_client_completion(mock_cost: MagicMock, mock_router: MagicMock) -> None:
    """Tests completion call, token tracking, and cost calculation."""
    mock_router_instance = MagicMock()
    mock_router.return_value = mock_router_instance
    
    # Mock response structure
    mock_response = MagicMock()
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 120
    mock_response.usage.completion_tokens = 80
    mock_router_instance.completion.return_value = mock_response
    
    mock_cost.return_value = 0.004
    
    client = LiteLLMClient()
    response = client.completion(
        model="architect-model", 
        messages=[{"role": "user", "content": "Test prompt"}]
    )
    
    assert response == mock_response
    mock_router_instance.completion.assert_called_once_with(
        model="architect-model",
        messages=[{"role": "user", "content": "Test prompt"}]
    )
    
    # Check metrics
    metrics = client.get_metrics()
    assert metrics["total_prompt_tokens"] == 120
    assert metrics["total_completion_tokens"] == 80
    assert metrics["total_tokens"] == 200
    assert metrics["total_cost_usd"] == 0.004

@patch("src.integrations.litellm_client.Router")
def test_litellm_client_fallback_failure(mock_router: MagicMock) -> None:
    """Tests that exceptions are raised correctly when router execution fails."""
    mock_router_instance = MagicMock()
    mock_router.return_value = mock_router_instance
    mock_router_instance.completion.side_effect = Exception("API Connection Error")
    
    client = LiteLLMClient()
    with pytest.raises(Exception, match="API Connection Error"):
        client.completion(model="coder-model", messages=[])
