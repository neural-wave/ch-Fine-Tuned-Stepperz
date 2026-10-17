"""API pubblica compatibile; implementazione in parsing.parser."""
from .parsing.parser import analyze, to_tree, isolate_subquery_scopes

__all__ = ['analyze', 'to_tree', 'isolate_subquery_scopes']
