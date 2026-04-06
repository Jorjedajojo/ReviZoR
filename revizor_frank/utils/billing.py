"""Billing utilities for ReviZoR.

Business rules for deposit percentage and service expiry window are pending
confirmation. See TODO comments below.
"""

from __future__ import annotations

# TODO: confirm with Sylvia — what percentage of the package value is retained
# as a non-refundable deposit when the candidate does not respond?
DEPOSIT_RETENTION_PCT: float = 0.0  # e.g. 0.50 for 50%

# TODO: confirm with Sylvia — number of days before an unanswered service
# request is considered expired and the deposit rule kicks in
SERVICE_EXPIRY_DAYS: int = 0  # e.g. 14


def calculate_retention_fee(package_value: float, completion_pct: float) -> float:
    """Calculate the retention fee for a partially completed or abandoned service.

    Args:
        package_value:  Total value of the service package (in the billing currency).
        completion_pct: Proportion of the service already completed, 0.0–1.0.

    Returns:
        The fee amount to retain.  Currently returns 0 — logic pending.
    """
    # TODO: confirm with Sylvia — implement retention fee logic once business
    # rules for DEPOSIT_RETENTION_PCT and SERVICE_EXPIRY_DAYS are confirmed.
    pass
