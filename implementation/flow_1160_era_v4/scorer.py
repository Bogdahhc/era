"""V3 scorer shim.

The first v3 project keeps the v1 schedule contract and scorer so generated
candidate code remains comparable while v3 metadata is audited and promoted
incrementally.
"""

from implementation.flow_1160_era.scorer import *  # noqa: F401,F403
