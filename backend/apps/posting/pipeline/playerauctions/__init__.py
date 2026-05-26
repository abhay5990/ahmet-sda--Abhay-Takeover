"""PlayerAuctions payload pipeline — XLSX generation helpers.

PA bulk upload payloads are now produced by the pipeline lib's build_bulk()
via adapter.build_bulk(). The game-specific row builders in this package
(valorant.py) are kept as reference but are no longer called directly.
"""

from apps.posting.pipeline.playerauctions.common import rows_to_xlsx  # noqa: F401
