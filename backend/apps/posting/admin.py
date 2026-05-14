from django.contrib import admin

from .models import (
    CleanerConfig,
    ContentTemplate,
    OfferPool,
    OfferPoolActiveOffer,
    OfferPoolItem,
    PostingJob,
    PostingJobItem,
    PostingDefault,
    SchedulerHeartbeat,
    SubplatformLimit,
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
    list_display = ['game', 'marketplace', 'multiplier_low', 'multiplier_mid', 'multiplier_high', 'min_price', 'forced_ending', 'exchange_rate', 'sub_platform']
    list_filter = ['marketplace']


@admin.register(ContentTemplate)
class ContentTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'game', 'marketplace', 'template_type', 'updated_at']
    list_filter = ['game', 'marketplace', 'template_type']
    search_fields = ['name', 'game__name', 'game__slug']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(SubplatformLimit)
class SubplatformLimitAdmin(admin.ModelAdmin):
    list_display = ['store', 'game', 'sub_platform', 'max_offers', 'stock_reserve']
    list_filter = ['game', 'sub_platform']


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


# ── Offer Pool (Auto Restock) ────────────────────────────────────


class OfferPoolItemInline(admin.TabularInline):
    model = OfferPoolItem
    extra = 0
    fields = ['owned_product', 'status', 'order', 'pushed_at', 'target_offer_id', 'error_message']
    readonly_fields = ['pushed_at']
    raw_id_fields = ['owned_product']


@admin.register(OfferPool)
class OfferPoolAdmin(admin.ModelAdmin):
    list_display = ['id', 'listing', 'game', 'store', 'strategy', 'status', 'threshold', 'target_count', 'current_remote_count', 'last_checked_at']
    list_filter = ['status', 'strategy', 'game']
    raw_id_fields = ['listing', 'store']
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
