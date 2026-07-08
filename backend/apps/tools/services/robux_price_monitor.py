"""
Robux Price Monitor — proactive margin guard.

Runs every 30 minutes via APScheduler.

Logic:
  - Fetch cheapest available RbxCrate rate (cost per 1,000 R$)
  - Calculate required Eldorado sell price to achieve 10% net margin after 11% fees
  - Compare against configured sell price (default $6.00 / 1,000 R$)
  - If current sell price gives < 10% margin → send Telegram alert with suggested price
  - If price was previously in alert state and margin is now OK → send recovery alert
  - Suppresses repeat alerts: only re-alerts if rate changes by >$0.10 since last alert

Margin formula:
  net_received  = sell_price * (1 - 0.11)   # after 11% Eldorado fees
  margin        = (net_received - cost) / net_received
  required_sell = cost / ((1 - 0.11) * (1 - 0.10))  # to hit exactly 10% margin

State is stored in Django cache (in-memory, survives scheduler restarts via DB cache).
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_UP

from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

ELDORADO_FEE_RATE = Decimal('0.11')       # 5% platform + 6% withdrawal
MIN_MARGIN = Decimal('0.10')              # 10% minimum net margin
ALERT_RATE_DELTA = Decimal('0.10')        # only re-alert if rate changed by >$0.10
CACHE_KEY_LAST_RATE = 'robux_monitor_last_alert_rate'
CACHE_KEY_ALERT_STATE = 'robux_monitor_alert_active'
CACHE_TIMEOUT = 60 * 60 * 24 * 7         # 7 days


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_telegram_creds():
    """Return (bot_token, chat_id) preferring the Robux bot."""
    try:
        from apps.integrations.models import ServiceCredential
        cred = ServiceCredential.objects.filter(
            service_type='telegram', slug='telegram-robux-bot', is_active=True
        ).first() or ServiceCredential.objects.filter(
            service_type='telegram', is_active=True
        ).first()
        if not cred:
            return None, None
        c = cred.credentials or {}
        return c.get('bot_token', ''), c.get('chat_id', '')
    except Exception as exc:
        logger.error('robux_monitor: telegram creds error: %s', exc)
        return None, None


def _telegram_send(bot_token: str, chat_id: str, text: str) -> None:
    import requests
    try:
        requests.post(
            f'https://api.telegram.org/bot{bot_token}/sendMessage',
            json={'chat_id': chat_id, 'text': text},
            timeout=10,
        )
    except Exception as exc:
        logger.warning('robux_monitor: telegram send failed: %s', exc)


def _get_cheapest_rbxcrate_rate() -> Decimal | None:
    """Return cheapest available RbxCrate rate ($/1000 R$) with stock > 0."""
    try:
        from apps.integrations.models import ServiceCredential
        from apps.integrations.services.robuxcrate import RobuxCrateService
        cred = ServiceCredential.objects.filter(
            service_type='robuxcrate', is_active=True
        ).first()
        if not cred:
            logger.warning('robux_monitor: no RbxCrate credential')
            return None
        facade = RobuxCrateService.build_client(cred)
        result = facade.get_detailed_stock()
        if not result.ok or not result.data:
            logger.warning('robux_monitor: get_detailed_stock failed: %s', result.error)
            return None
        # Find cheapest tier with meaningful stock (>= 1,000 R$)
        tiers = [
            t for t in result.data
            if t.get('totalRobuxAmount', 0) >= 1000
        ]
        if not tiers:
            return None
        cheapest = min(tiers, key=lambda t: t['rate'])
        return Decimal(str(cheapest['rate']))
    except Exception as exc:
        logger.error('robux_monitor: get_cheapest_rate error: %s', exc)
        return None


def _get_configured_sell_price() -> Decimal:
    """Return configured Eldorado sell price per 1,000 R$ from DB or default $6.00."""
    try:
        from django.core.cache import cache
        price = cache.get('robux_monitor_sell_price')
        if price:
            return Decimal(str(price))
    except Exception:
        pass
    return Decimal('6.00')


def _required_sell_price(cost_per_1000: Decimal) -> Decimal:
    """Calculate minimum sell price to achieve MIN_MARGIN after fees."""
    # net_received = sell * (1 - fee)
    # margin = (net_received - cost) / net_received >= MIN_MARGIN
    # => sell * (1 - fee) * (1 - margin) >= cost
    # => sell >= cost / ((1 - fee) * (1 - margin))
    denominator = (1 - ELDORADO_FEE_RATE) * (1 - MIN_MARGIN)
    required = cost_per_1000 / denominator
    # Round up to nearest $0.05
    return (required / Decimal('0.05')).to_integral_value(rounding=ROUND_UP) * Decimal('0.05')


def _calc_margin(sell_price: Decimal, cost_per_1000: Decimal) -> Decimal:
    """Calculate actual net margin."""
    net = sell_price * (1 - ELDORADO_FEE_RATE)
    if net <= 0:
        return Decimal('-1')
    return (net - cost_per_1000) / net


# ── Main monitor function ─────────────────────────────────────────────────────

def run_robux_price_monitor() -> None:
    """Main entry point — called by APScheduler every 30 minutes."""
    logger.info('robux_monitor: checking RbxCrate rates...')

    cost = _get_cheapest_rbxcrate_rate()
    if cost is None:
        logger.warning('robux_monitor: could not fetch rate, skipping')
        return

    sell_price = _get_configured_sell_price()
    margin = _calc_margin(sell_price, cost)
    required = _required_sell_price(cost)
    margin_pct = float(margin * 100)

    logger.info(
        'robux_monitor: cost=$%.2f/1000R$, sell=$%.2f/1000R$, margin=%.1f%%, required_sell=$%.2f',
        cost, sell_price, margin_pct, required,
    )

    try:
        from django.core.cache import cache
        last_alert_rate = cache.get(CACHE_KEY_LAST_RATE)
        alert_active = cache.get(CACHE_KEY_ALERT_STATE, False)

        bot_token, chat_id = _get_telegram_creds()

        if margin < MIN_MARGIN:
            # Check if we should suppress (rate hasn't changed much since last alert)
            if last_alert_rate is not None:
                rate_delta = abs(cost - Decimal(str(last_alert_rate)))
                if rate_delta < ALERT_RATE_DELTA and alert_active:
                    logger.info('robux_monitor: margin low but rate unchanged, suppressing repeat alert')
                    return

            # Send alert
            profit_per_1000 = sell_price * (1 - ELDORADO_FEE_RATE) - cost
            msg = (
                f"\u26a0\ufe0f Robux Margin Alert\n\n"
                f"RbxCrate cheapest rate : ${cost:.2f} / 1,000 R$\n"
                f"Your Eldorado price    : ${sell_price:.2f} / 1,000 R$\n"
                f"After 11% fees         : ${float(sell_price * (1 - ELDORADO_FEE_RATE)):.2f} / 1,000 R$\n"
                f"Net profit             : ${float(profit_per_1000):.2f} / 1,000 R$ ({margin_pct:.1f}%)\n\n"
                f"Minimum margin target  : 10%\n"
                f"Suggested sell price   : ${required:.2f} / 1,000 R$\n\n"
                f"Action: Raise your Eldorado Roblox listing price to ${required:.2f} per 1,000 R$."
            )
            if bot_token and chat_id:
                _telegram_send(bot_token, chat_id, msg)
            logger.warning('robux_monitor: MARGIN ALERT sent — cost=$%.2f, margin=%.1f%%', cost, margin_pct)

            cache.set(CACHE_KEY_LAST_RATE, float(cost), CACHE_TIMEOUT)
            cache.set(CACHE_KEY_ALERT_STATE, True, CACHE_TIMEOUT)

        else:
            # Margin is OK
            if alert_active:
                # Recovery — margin was previously bad, now it's good
                profit_per_1000 = sell_price * (1 - ELDORADO_FEE_RATE) - cost
                msg = (
                    f"\u2705 Robux Margin Restored\n\n"
                    f"RbxCrate cheapest rate : ${cost:.2f} / 1,000 R$\n"
                    f"Your Eldorado price    : ${sell_price:.2f} / 1,000 R$\n"
                    f"Net profit             : ${float(profit_per_1000):.2f} / 1,000 R$ ({margin_pct:.1f}%)\n\n"
                    f"Margin is back above 10% — safe to sell."
                )
                if bot_token and chat_id:
                    _telegram_send(bot_token, chat_id, msg)
                logger.info('robux_monitor: margin restored to %.1f%%', margin_pct)
                cache.set(CACHE_KEY_ALERT_STATE, False, CACHE_TIMEOUT)
                cache.set(CACHE_KEY_LAST_RATE, float(cost), CACHE_TIMEOUT)
            else:
                logger.info('robux_monitor: margin OK at %.1f%% — no alert needed', margin_pct)

    except Exception as exc:
        logger.error('robux_monitor: unexpected error: %s', exc)
