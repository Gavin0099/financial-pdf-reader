"""
Reasoning Patterns — Package root
Exports PATTERN_REGISTRY: ordered list of all 6 PatternDefinition objects.
"""
from reasoning_patterns.patterns.operating_vs_net_income import PATTERN as P1
from reasoning_patterns.patterns.non_recurring_eps import PATTERN as P2
from reasoning_patterns.patterns.fx_driven_profit import PATTERN as P3
from reasoning_patterns.patterns.expense_ratio_offset import PATTERN as P4
from reasoning_patterns.patterns.debt_maturity_risk import PATTERN as P5
from reasoning_patterns.patterns.customer_concentration import PATTERN as P6

PATTERN_REGISTRY = [P1, P2, P3, P4, P5, P6]

__all__ = ["PATTERN_REGISTRY"]
