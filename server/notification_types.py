"""Shared error type for worker modules, including python -m entry points."""

class DeliveryError(Exception):
    def __init__(self, retry_after=60, status=None):
        self.status=status
        self.retry_after=max(60,min(86400,retry_after))
