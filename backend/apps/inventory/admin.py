from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe

from .models import Category, Game, GamePlatformMapping, OwnedProduct, DropshipProduct


class GamePlatformMappingInline(admin.TabularInline):
    model = GamePlatformMapping
    extra = 1
    fields = ('platform', 'external_id', 'external_name')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('title', 'name', 'category_id', 'game_count')
    search_fields = ('name', 'title')

    @admin.display(description='Games')
    def game_count(self, obj):
        return obj.games.count()


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'acronym', 'category', 'platform_count', 'is_active')
    list_filter = ('is_active', 'category')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'acronym', 'slug')
    inlines = [GamePlatformMappingInline]

    @admin.display(description='Platforms')
    def platform_count(self, obj):
        return obj.platform_mappings.count()


@admin.register(GamePlatformMapping)
class GamePlatformMappingAdmin(admin.ModelAdmin):
    list_display = ('game', 'platform', 'external_id', 'external_name')
    list_filter = ('platform',)
    search_fields = ('game__name', 'external_id', 'external_name')
    raw_id_fields = ('game',)


@admin.register(OwnedProduct)
class OwnedProductAdmin(admin.ModelAdmin):
    list_display = ('login', 'category', 'game', 'status', 'price', 'currency', 'source_account', 'created_at')
    list_select_related = ('category', 'game', 'source_account')

    def get_queryset(self, request):
        return super().get_queryset(request).defer('raw_data')

    list_filter = ('status', 'category')
    search_fields = ('login', 'email')
    show_full_result_count = False
    list_per_page = 50
    readonly_fields = ('password_hash', 'created_at', 'updated_at', 'linked_orders', 'linked_listings')
    raw_id_fields = ('game', 'source_account', 'product_origin')
    fieldsets = (
        (None, {
            'fields': ('category', 'game', 'status'),
        }),
        ('Credentials', {
            'fields': ('login', 'password', 'password_hash', 'email', 'email_password', 'email_login_link'),
        }),
        ('Security Email', {
            'fields': ('security_email', 'security_email_password', 'security_email_login_link'),
            'classes': ('collapse',),
        }),
        ('Purchase Info', {
            'fields': ('price', 'currency', 'purchased_at', 'source_account', 'product_origin'),
        }),
        ('Linked Items', {
            'fields': ('linked_orders', 'linked_listings'),
        }),
        ('Data', {
            'fields': ('raw_data',),
            'classes': ('collapse',),
        }),
        ('Meta', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    @admin.display(description='Linked Orders')
    def linked_orders(self, obj):
        orders = obj.orders.select_related('integration_account').order_by('-sold_at')[:10]
        if not orders:
            return mark_safe('<em style="color: gray;">None</em>')
        return format_html_join(
            mark_safe('<br>'),
            '<a href="{}">{} — {} ({})</a>',
            (
                (
                    reverse('admin:orders_order_change', args=[o.pk]),
                    o.store_order_id,
                    o.integration_account.slug if o.integration_account else '?',
                    o.status,
                )
                for o in orders
            ),
        )

    @admin.display(description='Linked Listings')
    def linked_listings(self, obj):
        from apps.listings.models import Listing
        listings = (
            Listing.objects
            .filter(listing_owned_products__owned_product=obj)
            .select_related('integration_account')[:10]
        )
        if not listings:
            return mark_safe('<em style="color: gray;">None</em>')
        return format_html_join(
            mark_safe('<br>'),
            '<a href="{}">{} — {} [{}]</a>',
            (
                (
                    reverse('admin:listings_listing_change', args=[l.pk]),
                    (l.title or '')[:40],
                    l.integration_account.slug if l.integration_account else '?',
                    l.status,
                )
                for l in listings
            ),
        )


@admin.register(DropshipProduct)
class DropshipProductAdmin(admin.ModelAdmin):
    list_display = ('product_title', 'source_product_id', 'source_account', 'category', 'status', 'price', 'currency')
    list_select_related = ('source_account', 'category', 'game')
    list_filter = ('status', 'category', 'source_account')
    search_fields = ('product_title', 'source_product_id')
    show_full_result_count = False
    list_per_page = 50
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('product_title', 'category', 'game', 'status'),
        }),
        ('Source', {
            'fields': ('source_product_id', 'source_account', 'source_url'),
        }),
        ('Pricing', {
            'fields': ('price', 'currency'),
        }),
        ('Data', {
            'fields': ('raw_data',),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('last_checked_at', 'deleted_at', 'created_at', 'updated_at'),
        }),
    )
