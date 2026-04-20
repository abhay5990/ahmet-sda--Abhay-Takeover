"""PA Bulk Uploader — generic XLSX upload + row-error retry.

Responsibilities:
- Write Excel rows to a temp file
- POST to PA bulk upload endpoint via facade
- Parse row-specific errors and retry without the bad row (max 3 attempts)
- Return per-row results (success → offer_id, failure → error message)

Does NOT know about games, payload format, or database — pure HTTP orchestration.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_ROW_ERROR_PATTERN = re.compile(r'\brow\s*(\d+)\b', re.IGNORECASE)
_MAX_RETRIES = 3


@dataclass
class PABatchResult:
    """Per-row upload result.

    Keys in both dicts are original row indices (0-based).
    successful: {orig_idx: offer_id_str}
    failed:     {orig_idx: error_message_str}
    """
    successful: dict[int, str] = field(default_factory=dict)
    failed: dict[int, str] = field(default_factory=dict)


class PABulkUploader:
    """Uploads a list of Excel row dicts to PlayerAuctions bulk upload endpoint.

    Usage:
        uploader = PABulkUploader()
        result = uploader.upload_batch(facade, rows, proxy_group=proxy_group)
        # result.successful = {0: "12345678", 2: "12345679"}
        # result.failed     = {1: "Invalid input in row 3"}
    """

    def upload_batch(
        self,
        facade,
        rows: list[dict[str, Any]],
        *,
        proxy_group: str | None = None,
    ) -> PABatchResult:
        """Upload rows to PA. Returns per-original-index results.

        Strategy:
        1. Build XLSX from all rows.
        2. POST to PA bulk upload endpoint.
        3. If row-specific error → remove that row, retry remaining (max 3 attempts).
        4. If non-row error → fail all remaining rows.
        5. Map PA offer IDs back to original indices by insertion order.
        """
        result = PABatchResult()

        if not rows:
            return result

        # Work with (original_index, row_dict) pairs so we track original position
        remaining: list[tuple[int, dict[str, Any]]] = list(enumerate(rows))

        for attempt in range(1, _MAX_RETRIES + 1):
            if not remaining:
                break

            logger.debug(
                "PA bulk upload attempt %d/%d — %d rows",
                attempt, _MAX_RETRIES, len(remaining),
            )

            xlsx_bytes = self._build_xlsx([row for _, row in remaining])
            api_result = self._upload(facade, xlsx_bytes, proxy_group=proxy_group)

            if api_result['ok']:
                # All rows accepted — map offer IDs by order
                offers: list[dict] = api_result.get('offers', [])
                for i, (orig_idx, _) in enumerate(remaining):
                    offer_id = ''
                    if i < len(offers):
                        offer = offers[i]
                        offer_id = str(
                            offer.get('offerId') or offer.get('OfferId') or ''
                        )
                    result.successful[orig_idx] = offer_id
                remaining = []
                break

            # Upload failed — check if row-specific
            error_msg: str = api_result.get('error', 'Unknown PA upload error')
            row_num = self._extract_row_number(error_msg)

            if row_num is None:
                # Non-row-specific error — fail all remaining
                logger.warning("PA upload non-row error: %s", error_msg)
                for orig_idx, _ in remaining:
                    result.failed[orig_idx] = error_msg
                remaining = []
                break

            # Row N is bad (1-indexed, row 1 = header → row 2 = rows[0])
            bad_batch_idx = row_num - 2  # convert to 0-based batch index
            if 0 <= bad_batch_idx < len(remaining):
                orig_idx, _ = remaining.pop(bad_batch_idx)
                result.failed[orig_idx] = f'Row rejected: {error_msg}'
                logger.warning(
                    "PA upload row error at batch row %d (orig_idx=%d): %s",
                    bad_batch_idx, orig_idx, error_msg,
                )
            else:
                # Row number out of range — can't recover, fail all
                logger.warning(
                    "PA upload row error with unparseable row number %d "
                    "(batch size=%d): %s",
                    row_num, len(remaining), error_msg,
                )
                for orig_idx, _ in remaining:
                    result.failed[orig_idx] = error_msg
                remaining = []
                break

        # Anything still in remaining after max retries = failed
        for orig_idx, _ in remaining:
            result.failed[orig_idx] = 'Max retries exceeded without success'

        logger.info(
            "PA batch done: %d successful, %d failed",
            len(result.successful), len(result.failed),
        )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _build_xlsx(rows: list[dict[str, Any]]) -> bytes:
        """Convert row dicts to XLSX bytes via the pipeline common builder."""
        from apps.posting.pipeline.playerauctions.common import rows_to_xlsx
        return rows_to_xlsx(rows)

    @staticmethod
    def _upload(
        facade,
        xlsx_bytes: bytes,
        *,
        proxy_group: str | None = None,
    ) -> dict[str, Any]:
        """Write bytes to a temp file, call facade.bulk_upload(), return normalized dict.

        Returns:
            {'ok': True, 'offers': [...]}
            {'ok': False, 'error': '...'}
        """
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix='.xlsx', delete=False,
            ) as tmp:
                tmp.write(xlsx_bytes)
                tmp_path = tmp.name

            kwargs: dict[str, Any] = {}
            if proxy_group:
                kwargs['proxy_group'] = proxy_group

            api_result = facade.bulk_upload(tmp_path, **kwargs)

            if api_result.ok and api_result.data:
                return {'ok': True, 'offers': api_result.data.offers or []}

            error_msg = ''
            if api_result.error:
                error_msg = str(api_result.error.message or '')
            return {'ok': False, 'error': error_msg or 'PA bulk upload returned failure'}

        except Exception as exc:
            logger.exception("PA bulk upload transport error")
            return {'ok': False, 'error': str(exc)}
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @staticmethod
    def _extract_row_number(error_msg: str) -> int | None:
        """Extract the 1-based row number from a PA error message.

        PA error messages look like: 'Invalid input in row 3' or 'row3'.
        Returns None if no row number found.
        """
        match = _ROW_ERROR_PATTERN.search(error_msg)
        if match:
            return int(match.group(1))
        return None
