"""
Cost tracking and estimation for LLM usage.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from src.core.config import config

logger = logging.getLogger(__name__)

@dataclass
class CostTracker:
    """
    Tracks costs across API calls and provides threshold warnings.
    """
    model_name: str = field(default=config.MODEL_NAME)
    total_cost: float = 0.0
    
    def calculate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate the estimated cost for a given token usage."""
        input_cost = (prompt_tokens / 1_000_000) * config.MODEL_COST_INPUT_1M
        output_cost = (completion_tokens / 1_000_000) * config.MODEL_COST_OUTPUT_1M
        
        return input_cost + output_cost

    def add_usage(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Add usage and return the incremental cost."""
        cost = self.calculate_cost(prompt_tokens, completion_tokens)
        self.total_cost += cost
        
        if self.total_cost > config.COST_WARNING_THRESHOLD:
            logger.warning(
                f"Cost threshold exceeded! Total cost: ${self.total_cost:.4f} "
                f"(Threshold: ${config.COST_WARNING_THRESHOLD:.4f})"
            )
            
        return cost

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of usage and costs."""
        return {
            "model_name": self.model_name,
            "total_cost_usd": round(self.total_cost, 6),
            "threshold_exceeded": self.total_cost > config.COST_WARNING_THRESHOLD
        }
