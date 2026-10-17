"""API pubblica compatibile; implementazione in governance.adequacy."""
from .governance.adequacy import ShaclContext, AdequacySummary, validate_adequacy, SH

__all__ = ['ShaclContext', 'AdequacySummary', 'validate_adequacy', 'SH']
