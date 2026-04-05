class InventoryManagerException(Exception):
    """Base exception for the inventory manager project."""
    pass


class MarketplaceAPIError(InventoryManagerException):
    """Raised when a marketplace API call fails."""
    def __init__(self, marketplace: str, message: str, status_code: int | None = None):
        self.marketplace = marketplace
        self.status_code = status_code
        super().__init__(f"[{marketplace}] {message} (status={status_code})")


class AdapterNotFoundError(InventoryManagerException):
    """Raised when a marketplace adapter is not found."""
    def __init__(self, marketplace: str):
        super().__init__(f"No adapter registered for marketplace: {marketplace}")


class DuplicateListingError(InventoryManagerException):
    """Raised when trying to create a listing that already exists."""
    pass


class InsufficientStockError(InventoryManagerException):
    """Raised when product stock is insufficient for an operation."""
    pass
