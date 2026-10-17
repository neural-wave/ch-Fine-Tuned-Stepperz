"""API pubblica compatibile; implementazione in governance.privacy."""
from .governance.privacy import ExecutionContext, ReleaseHistory, preflight, snapshot_digest

__all__ = ['ExecutionContext', 'ReleaseHistory', 'preflight', 'snapshot_digest']
