"""The single public JLC-R algorithm entry point.

The implementation bytes remain in v63_model.py for evidence-hash continuity.
Supporting parent modules are dependencies, not separate public releases.
"""
from v63_model import RelayRepairHYB as JLCR
__all__=['JLCR']
