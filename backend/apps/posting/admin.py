from django.contrib import admin
from django.http import JsonResponse
from django.urls import path

from .models import (
    CleanerConfig,
    ContentTemplate,
    CredentialSpec,
    GameVariant,
    GameVariantLimit,
    GameVariantMapping,
    OfferPool,
    OfferPoolActiveOffer,
    OfferPoolItem,
    PostingJob,
    PostingJobItem,
    PostingImagePreset,
    PostingDefault,
    SchedulerHeartbeat,
    PostingLog,
    DropshippingJobConfig,
    DropshipTargetURL,
)


@admin.register(PostingJob)
class PostingJobAdmin(admin.ModelAdmin):
    list_display = ['id', 'game', 'status', 'total_count', 'success_count', 'fail_count', 'created_at', 'completed_at']
    list_filter = ['status', 'game']
    readonly_fields = ['created_at', 'completed_at']
    ordering = ['-created_at']


@admin.register(PostingJobItem)
class PostingJobItemAdmin(admin.ModelAdmin):
    list_display = ['id', 'job', 'owned_product', 'store', 'marketplace', 'status', 'updated_at']
    list_filter = ['status', 'marketplace']
    raw_id_fields = ['job', 'owned_product', 'store', 'listing']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PostingDefault)
class PostingDefaultAdmin(admin.ModelAdmin):
    list_display = ['game', 'marketplace', 'multiplier_low', 'multiplier_mid', 'multiplier_high', 'min_price', 'forced_ending', 'exchange_rate', 'variant']
    list_filter = ['marketplace']


@admin.register(ContentTemplate)
class ContentTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'game', 'marketplace', 'template_type', 'updated_at']
    list_filter = ['game', 'marketplace', 'template_type']
    search_fields = ['name', 'game__name', 'game__slug']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(PostingImagePreset)
class PostingImagePresetAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'game', 'user', 'is_active', 'width', 'height', 'created_at', 'last_used_at']
    list_filter = ['game', 'is_active']
    search_fields = ['name', 'sha256', 'user__username']
    readonly_fields = ['sha256', 'mime_type', 'size_bytes', 'width', 'height', 'created_at', 'updated_at', 'last_used_at']
    raw_id_fields = ['user', 'game']


# ── Game Variant System ──────────────────────────────────────────


class GameVariantMappingInline(admin.TabularInline):
    model = GameVariantMapping
    extra = 0
    fields = ['marketplace', 'external_id', 'external_name']


@admin.register(GameVariant)
class GameVariantAdmin(admin.ModelAdmin):
    list_display = ['game', 'type', 'slug', 'label', 'source_key', 'sort_order']
    list_filter = ['type', 'game']
    search_fields = ['slug', 'label', 'game__name']
    ordering = ['game', 'type', 'sort_order']
    inlines = [GameVariantMappingInline]


@admin.register(GameVariantMapping)
class GameVariantMappingAdmin(admin.ModelAdmin):
    list_display = ['variant', 'marketplace', 'external_id', 'external_name']
    list_filter = ['marketplace']
    raw_id_fields = ['variant']


@admin.register(GameVariantLimit)
class GameVariantLimitAdmin(admin.ModelAdmin):
    list_display = ['store', 'variant', 'max_offers', 'stock_reserve']
    list_filter = ['variant__game', 'variant__type']
    raw_id_fields = ['store', 'variant']


@admin.register(PostingLog)
class PostingLogAdmin(admin.ModelAdmin):
    list_display = ['task_name', 'level', 'message', 'integration_account', 'created_at']
    list_filter = ['level', 'task_name']
    readonly_fields = ['created_at', 'detail']
    ordering = ['-created_at']


class DropshipTargetURLInline(admin.TabularInline):
    model = DropshipTargetURL
    extra = 0
    fields = ['url', 'enabled', 'multiplier_low', 'multiplier_mid', 'multiplier_high', 'min_price', 'forced_ending', 'exchange_rate', 'items_found', 'items_posted']
    readonly_fields = ['items_found', 'items_posted']


@admin.register(DropshippingJobConfig)
class DropshippingJobConfigAdmin(admin.ModelAdmin):
    list_display = ['source_account', 'store', 'game', 'enabled', 'item_delay', 'source_delay', 'created_at']
    list_filter = ['enabled', 'game']
    raw_id_fields = ['source_account', 'store']
    inlines = [DropshipTargetURLInline]


@admin.register(DropshipTargetURL)
class DropshipTargetURLAdmin(admin.ModelAdmin):
    list_display = ['config', 'url', 'enabled', 'items_found', 'items_posted', 'last_fetched_at', 'error_count']
    list_filter = ['enabled']
    raw_id_fields = ['config']
    readonly_fields = ['last_fetched_at', 'items_found', 'items_posted', 'error_count', 'last_error', 'created_at']


@admin.register(CleanerConfig)
class CleanerConfigAdmin(admin.ModelAdmin):
    list_display = ['source_account', 'enabled', 'running', 'disabled_reason', 'cycle_interval', 'last_cycle_at']
    list_filter = ['enabled', 'running']
    raw_id_fields = ['source_account']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(SchedulerHeartbeat)
class SchedulerHeartbeatAdmin(admin.ModelAdmin):
    list_display = ['service_name', 'last_seen', 'pid', 'started_at']
    readonly_fields = ['service_name', 'last_seen', 'pid', 'started_at']


# ── Credential Spec ──────────────────────────────────────────────


@admin.register(CredentialSpec)
class CredentialSpecAdmin(admin.ModelAdmin):
    list_display = ['name', 'game', 'variant', 'is_active', 'updated_at']
    list_filter = ['is_active', 'game']
    search_fields = ['name', 'game__name']
    readonly_fields = ['name', 'created_at', 'updated_at']

    def get_fields(self, request, obj=None):
        return ['game', 'variant', 'name', 'fields', 'format_templates', 'is_active', 'created_at', 'updated_at']

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'variants-for-game/<int:game_id>/',
                self.admin_site.admin_view(self._variants_for_game),
                name='credentialspec_variants_for_game',
            ),
        ]
        return custom + urls

    def _variants_for_game(self, request, game_id):
        variants = GameVariant.objects.filter(game_id=game_id).order_by('type', 'sort_order')
        data = [{'id': v.id, 'label': f"{v.get_type_display()}: {v.label} ({v.slug})"} for v in variants]
        return JsonResponse({'variants': data})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'variant':
            obj_id = request.resolver_match.kwargs.get('object_id')
            if obj_id:
                # Edit mode: show only variants for this spec's game
                try:
                    spec = CredentialSpec.objects.get(pk=obj_id)
                    kwargs['queryset'] = GameVariant.objects.filter(game=spec.game)
                except CredentialSpec.DoesNotExist:
                    kwargs['queryset'] = GameVariant.objects.none()
            else:
                # Create mode: start empty, JS will populate on game change
                kwargs['queryset'] = GameVariant.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        # Force re-generate name from game + variant (name is readonly in admin)
        obj.name = ''
        super().save_model(request, obj, form, change)

    class Media:
        js = ('admin/js/credential_spec_variant_filter.js',)


# ── Offer Pool (Auto Restock) ────────────────────────────────────


class OfferPoolItemInline(admin.TabularInline):
    model = OfferPoolItem
    extra = 0
    fields = ['owned_product', 'status', 'order', 'pushed_at', 'target_offer_id', 'error_message']
    readonly_fields = ['pushed_at']
    raw_id_fields = ['owned_product']


@admin.register(OfferPool)
class OfferPoolAdmin(admin.ModelAdmin):
    list_display = ['id', 'listing', 'game', 'store', 'strategy', 'status', 'credential_spec', 'threshold', 'target_count', 'current_remote_count', 'last_checked_at']
    list_filter = ['status', 'strategy', 'game']
    raw_id_fields = ['listing', 'store', 'credential_spec']
    readonly_fields = ['current_remote_count', 'last_checked_at', 'last_replenished_at', 'created_at', 'updated_at']
    inlines = [OfferPoolItemInline]


@admin.register(OfferPoolItem)
class OfferPoolItemAdmin(admin.ModelAdmin):
    list_display = ['id', 'pool', 'owned_product', 'status', 'order', 'pushed_at', 'target_offer_id']
    list_filter = ['status']
    raw_id_fields = ['pool', 'owned_product']
    readonly_fields = ['pushed_at', 'created_at', 'updated_at']


@admin.register(OfferPoolActiveOffer)
class OfferPoolActiveOfferAdmin(admin.ModelAdmin):
    list_display = ['id', 'pool', 'store_listing_id', 'status', 'created_at']
    list_filter = ['status']
    raw_id_fields = ['pool', 'listing', 'pool_item']
    readonly_fields = ['created_at', 'updated_at']
