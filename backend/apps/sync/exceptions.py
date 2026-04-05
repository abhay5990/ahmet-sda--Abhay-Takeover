class SkipItem(Exception):
    """Raised by provider hooks to skip an item entirely.

    When raised from ``prepare_item``, the item is not written to
    ``RawPayload`` and the loop continues to the next item.
    The item is still counted as processed.
    """


class StopSync(Exception):
    """Raised by provider hooks to abort the entire sync run.

    When raised from ``prepare_item``, the sync run is marked as
    failed and the exception propagates to the caller.

    Example: Eldorado enrichment failure for instant account orders.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
