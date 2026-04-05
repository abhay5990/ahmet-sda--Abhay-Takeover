from django.contrib import admin

from .models import Listing, ListingOwnedProduct


class OwnedProductLinkFilter(admin.SimpleListFilter):
    title = 'OwnedProduct link'
    parameter_name = 'op_link'

    def lookups(self, request, model_admin):
        return [
            ('yes', 'Linked'),
            ('no', 'Unlinked'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(listing_owned_products__isnull=False).distinct()
        if self.value() == 'no':
            return queryset.exclude(listing_owned_products__isnull=False)
        return queryset


class ListingOwnedProductInline(admin.TabularInline):
    model = ListingOwnedProduct
    extra = 1
    raw_id_fields = ('owned_product',)


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'integration_account',
        'status',
        'price',
        'store_listing_id',
        'listed_at',
    )
    list_select_related = ('integration_account', 'game')

    def get_queryset(self, request):
        return super().get_queryset(request).defer('raw_data')

    list_filter = ('status', 'integration_account', OwnedProductLinkFilter)
    search_fields = ('title', 'store_listing_id')
    readonly_fields = ('created_at', 'updated_at')
    show_full_result_count = False
    list_per_page = 50
    inlines = [ListingOwnedProductInline]
