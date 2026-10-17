"""API pubblica compatibile; implementazione in configuration.policy."""
from .configuration.policy import Policy, Check, CHECKS, DEFAULT_POLICY, OPERATOR_CHECKS

__all__ = ['Policy', 'Check', 'CHECKS', 'DEFAULT_POLICY', 'OPERATOR_CHECKS']
