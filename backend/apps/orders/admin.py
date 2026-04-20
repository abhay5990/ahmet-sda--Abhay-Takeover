from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.inventory.enums import OwnedProductStatus
from apps.inventory.services import resolve_game
from apps.sync.services.shared.credentials import parse_credentials_text
from apps.sync.services.shared.owned_product import get_or_create_owned_product

from .models import FeeRule, Order


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

class OwnedProductMatchFilter(admin.SimpleListFilter):
    title = 'OwnedProduct match'
    parameter_name = 'op_match'

    def lookups(self, request, model_admin):
        return [
            ('yes', 'Matched'),
            ('no', 'Unmatched'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(owned_product__isnull=False)
        if self.value() == 'no':
            return queryset.filter(owned_product__isnull=True)
        return queryset


class IsInstantFilter(admin.SimpleListFilter):
    title = 'Instant'
    parameter_name = 'is_instant'

    def lookups(self, request, model_admin):
        return [('yes', 'Instant'), ('no', 'Manual/Dropship')]

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(is_instant=True)
        if self.value() == 'no':
            return queryset.filter(is_instant=False)
        return queryset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_credentials_text(raw_data: dict) -> str:
    """Extract raw credential text from order raw_data (multi-provider)."""
    if not raw_data:
        return ''

    # Gameboost: inline credentials
    text = raw_data.get('credentials') or ''
    if text:
        return text

    # Gameboost: _credential_entries
    entries = raw_data.get('_credential_entries', [])
    for entry in entries:
        cred = entry.get('credentials', '')
        if cred:
            return cred

    # Eldorado: accountDetails.secretDetails
    account_details = raw_data.get('accountDetails') or {}
    text = account_details.get('secretDetails', '')
    if text:
        return text

    # Eldorado: delivery_instructions fallback
    text = raw_data.get('delivery_instructions', '')
    return text


def _resolve_game_from_raw(order: Order):
    """Resolve (game, category) from order raw_data."""
    raw = order.raw_data or {}
    provider = order.integration_account.provider if order.integration_account else ''

    game_ext_id = ''

    if provider == 'gameboost':
        game = raw.get('game') or {}
        game_ext_id = str(game.get('id') or '')
    elif provider == 'eldorado':
        game_ext_id = str(raw.get('gameId') or '')
    elif provider == 'playerauctions':
        game_ext_id = str(raw.get('gameId') or raw.get('game_id') or '')

    if not game_ext_id:
        return None, None

    game = resolve_game(provider, game_ext_id)
    if game and game.category:
        return game, game.category
    return game, None


# ---------------------------------------------------------------------------
# Admin Actions
# ---------------------------------------------------------------------------

@admin.action(description='Create OwnedProduct & Link selected orders')
def create_owned_product_and_link(modeladmin, request, queryset):
    """Parse credentials from raw_data, create OwnedProduct, link to order."""
    success = 0
    skipped = 0
    errors = []

    orders = queryset.filter(
        owned_product__isnull=True,
        is_instant=True,
    ).exclude(
        status='cancelled',
    ).select_related('integration_account')

    for order in orders:
        try:
            # 1. Extract credentials text
            text = _extract_credentials_text(order.raw_data)
            if not text:
                skipped += 1
                continue

            # 2. Parse credentials
            parsed = parse_credentials_text(text)
            if not parsed.login:
                skipped += 1
                continue

            # 3. Resolve game/category
            game, category = _resolve_game_from_raw(order)
            if not category:
                skipped += 1
                continue

            # 4. Create or get OwnedProduct
            owned = get_or_create_owned_product(
                parsed=parsed,
                category=category,
                game=game,
                source_account=order.integration_account,
                status=OwnedProductStatus.SOLD,
                price=order.price / 2 if order.price else None,
                currency=order.currency,
                purchased_at=order.sold_at,
            )
            if not owned:
                skipped += 1
                continue

            # 5. Link order
            order.owned_product = owned
            order.save(update_fields=['owned_product', 'updated_at'])
            success += 1

        except Exception as e:
            errors.append(f'{order.store_order_id}: {e}')

    messages.success(request, f'{success} order(s) linked to OwnedProduct, {skipped} skipped.')
    if errors:
        messages.warning(
            request,
            f'{len(errors)} error(s): {"; ".join(errors[:5])}'
            + (f' ... and {len(errors) - 5} more' if len(errors) > 5 else ''),
        )


# ---------------------------------------------------------------------------
# OrderAdmin
# ---------------------------------------------------------------------------

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'store_order_id',
        'integration_account',
        'status',
        'is_instant',
        'price',
        'owned_product',
        'sold_at',
    )
    list_select_related = ('integration_account', 'owned_product', 'game')
    _raw_data_fields = (
        'owned_product__raw_data',
        'raw_data',
    )

    def get_queryset(self, request):
        return super().get_queryset(request).defer(*self._raw_data_fields)

    list_filter = (
        'status',
        'integration_account',
        OwnedProductMatchFilter,
        IsInstantFilter,
    )
    search_fields = ('store_order_id',)
    readonly_fields = ('created_at', 'updated_at', 'credentials_preview')
    raw_id_fields = ('owned_product', 'listing', 'dropship_product')
    show_full_result_count = False
    list_per_page = 50
    actions = [create_owned_product_and_link]

    @admin.display(description='Parsed Credentials')  # noqa: E303
    def credentials_preview(self, obj):
        """Show parsed credentials from raw_data on the detail page."""
        text = _extract_credentials_text(obj.raw_data)
        if not text:
            return mark_safe('<em style="color: gray;">No credentials in raw_data</em>')

        parsed = parse_credentials_text(text)

        rows = []
        for label, value in [
            ('Login', parsed.login),
            ('Password', parsed.password),
            ('Email', parsed.email),
            ('Email PW', parsed.email_password),
            ('Email Link', parsed.email_login_link),
            ('Security Email', parsed.security_email),
            ('Security PW', parsed.security_email_password),
        ]:
            if value:
                rows.append(format_html(
                    '<tr><td style="padding:2px 8px;font-weight:bold;">{}:</td>'
                    '<td style="padding:2px 8px;">{}</td></tr>',
                    label, value,
                ))

        if not rows:
            return mark_safe('<em style="color: orange;">Credentials found but nothing parsed</em>')

        return format_html(
            '<table style="border-collapse:collapse;">{}</table>',
            mark_safe(''.join(rows)),
        )


# ---------------------------------------------------------------------------
# FeeRuleAdmin
# ---------------------------------------------------------------------------

@admin.register(FeeRule)
class FeeRuleAdmin(admin.ModelAdmin):
    list_display = (
        'marketplace',
        'fee_type',
        'product_category_display',
        'game',
        'fee_percent',
        'flat_fee_display',
        'effective_from',
        'effective_until',
        'is_active',
    )
    list_filter = ('marketplace', 'fee_type', 'product_category')
    list_select_related = ('game',)
    raw_id_fields = ('game',)
    ordering = ('marketplace', 'fee_type', 'product_category', '-effective_from')
    list_per_page = 100

    fieldsets = (
        ('Rule Definition', {
            'fields': ('marketplace', 'fee_type', 'product_category', 'game'),
        }),
        ('Fee Values', {
            'fields': ('fee_percent', 'flat_fee', 'flat_fee_currency'),
        }),
        ('Validity Period', {
            'fields': ('effective_from', 'effective_until'),
        }),
        ('Note', {
            'fields': ('note',),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Category')
    def product_category_display(self, obj):
        return obj.get_product_category_display() if obj.product_category else '(all)'

    @admin.display(description='Flat Fee')
    def flat_fee_display(self, obj):
        if obj.flat_fee:
            return f'{obj.flat_fee} {obj.flat_fee_currency}'
        return '-'

    @admin.display(description='Active', boolean=True)
    def is_active(self, obj):
        from django.utils import timezone
        today = timezone.now().date()
        if obj.effective_until and obj.effective_until < today:
            return False
        return obj.effective_from <= today
