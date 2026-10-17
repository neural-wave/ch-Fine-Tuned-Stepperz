"""API pubblica compatibile; implementazione in execution.service."""
from .execution.service import execute_checked, ResultBlocked, UnsupportedExecution, check_payload, number, nodes, ExecutionContext, ReleaseHistory

__all__ = ['execute_checked', 'ResultBlocked', 'UnsupportedExecution', 'check_payload', 'number', 'nodes', 'ExecutionContext', 'ReleaseHistory']
