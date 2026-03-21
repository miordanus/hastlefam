"""autocat_service.py — Auto-categorization rules: merchant → tag.

Two modes:
1. Auto-learn: after a transaction is saved with a tag, check if the same
   merchant was tagged N times (threshold=3). If so, create/update a rule.
2. Apply: on capture, look up merchant in rules table. If found, return tag.

Rules are per-household, matched by case-insensitive merchant_pattern.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.infrastructure.db.models import MerchantTagRule, Transaction

log = logging.getLogger(__name__)

_AUTO_LEARN_THRESHOLD = 3


def _normalize_merchant(merchant: str) -> str:
    """Lowercase + strip for consistent matching."""
    return merchant.strip().lower()


def lookup_tag(db: Session, household_id, merchant: str) -> str | None:
    """Find a matching auto-cat rule for this merchant. Returns tag or None."""
    pattern = _normalize_merchant(merchant)
    if not pattern:
        return None

    rule = (
        db.query(MerchantTagRule)
        .filter(
            MerchantTagRule.household_id == household_id,
            MerchantTagRule.merchant_pattern == pattern,
            MerchantTagRule.is_active.is_(True),
        )
        .first()
    )
    if rule:
        rule.hit_count += 1
        rule.updated_at = datetime.now(timezone.utc)
        db.flush()
        return rule.tag
    return None


def learn_from_transaction(db: Session, household_id, merchant: str, tag: str) -> MerchantTagRule | None:
    """Check if this merchant+tag pair has been used enough times to create a rule.

    Called after every tagged capture. Returns the rule if created/updated, else None.
    """
    if not merchant or not tag:
        return None

    pattern = _normalize_merchant(merchant)
    if len(pattern) < 2:
        return None

    # Count how many times this merchant was tagged with this exact tag
    count = (
        db.query(func.count(Transaction.id))
        .filter(
            Transaction.household_id == household_id,
            func.lower(Transaction.merchant_raw) == pattern,
            Transaction.primary_tag == tag,
        )
        .scalar()
    )

    if count < _AUTO_LEARN_THRESHOLD:
        return None

    # Check if rule already exists
    existing = (
        db.query(MerchantTagRule)
        .filter(
            MerchantTagRule.household_id == household_id,
            MerchantTagRule.merchant_pattern == pattern,
        )
        .first()
    )

    if existing:
        if existing.tag == tag and existing.is_active:
            return None  # Already correct
        existing.tag = tag
        existing.is_active = True
        existing.source = "auto"
        existing.updated_at = datetime.now(timezone.utc)
        db.flush()
        log.info("auto-cat rule updated: %s → #%s", pattern, tag)
        return existing

    rule = MerchantTagRule(
        id=uuid.uuid4(),
        household_id=household_id,
        merchant_pattern=pattern,
        tag=tag,
        source="auto",
        hit_count=0,
        is_active=True,
    )
    db.add(rule)
    db.flush()
    log.info("auto-cat rule created: %s → #%s (after %d uses)", pattern, tag, count)
    return rule


def create_manual_rule(db: Session, household_id, merchant: str, tag: str) -> MerchantTagRule:
    """Explicitly create or update a rule via /rules command."""
    pattern = _normalize_merchant(merchant)

    existing = (
        db.query(MerchantTagRule)
        .filter(
            MerchantTagRule.household_id == household_id,
            MerchantTagRule.merchant_pattern == pattern,
        )
        .first()
    )

    if existing:
        existing.tag = tag
        existing.source = "manual"
        existing.is_active = True
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
        return existing

    rule = MerchantTagRule(
        id=uuid.uuid4(),
        household_id=household_id,
        merchant_pattern=pattern,
        tag=tag,
        source="manual",
        hit_count=0,
        is_active=True,
    )
    db.add(rule)
    db.commit()
    return rule


def delete_rule(db: Session, household_id, merchant: str) -> bool:
    """Soft-delete a rule. Returns True if found and deactivated."""
    pattern = _normalize_merchant(merchant)
    rule = (
        db.query(MerchantTagRule)
        .filter(
            MerchantTagRule.household_id == household_id,
            MerchantTagRule.merchant_pattern == pattern,
            MerchantTagRule.is_active.is_(True),
        )
        .first()
    )
    if not rule:
        return False
    rule.is_active = False
    rule.updated_at = datetime.now(timezone.utc)
    db.commit()
    return True


def list_rules(db: Session, household_id) -> list[MerchantTagRule]:
    """List all active rules for a household."""
    return (
        db.query(MerchantTagRule)
        .filter(
            MerchantTagRule.household_id == household_id,
            MerchantTagRule.is_active.is_(True),
        )
        .order_by(MerchantTagRule.hit_count.desc())
        .all()
    )
