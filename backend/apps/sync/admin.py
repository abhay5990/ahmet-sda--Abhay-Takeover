from django.contrib import admin
from django.utils.html import format_html

from .models import RawPayload, SyncCheckpoint, SyncFeatureFlag, SyncRun, SyncLog


@admin.register(RawPayload)
class RawPayloadAdmin(admin.ModelAdmin):
    list_display = (
        'remote_id',
        'resource_type',
        'integration_account',
        'parse_status_display',
        'parse_error_truncated',
        'fetched_at',
        'parsed_at',
    )
    list_select_related = ('integration_account',)

    def get_queryset(self, request):
        return super().get_queryset(request).defer('payload', 'meta')

    list_filter = ('resource_type', 'parse_status', 'integration_account')
    search_fields = ('remote_id',)
    show_full_result_count = False
    list_per_page = 50
    readonly_fields = (
        'integration_account',
        'resource_type',
        'remote_id',
        'payload',
        'parse_status',
        'parse_error',
        'meta',
        'payload_hash',
        'first_seen_at',
        'last_seen_at',
        'fetched_at',
        'parsed_at',
        'created_at',
        'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Last Error')
    def parse_error_truncated(self, obj):
        if not obj.parse_error:
            return ''
        if len(obj.parse_error) > 100:
            return obj.parse_error[:100] + '...'
        return obj.parse_error

    @admin.display(description='Parse Status')
    def parse_status_display(self, obj):
        colours = {
            'pending': 'orange',
            'parsed': 'green',
            'failed': 'red',
            'skipped': 'gray',
        }
        colour = colours.get(obj.parse_status, 'black')
        return format_html(
            '<span style="color: {};">{}</span>',
            colour,
            obj.get_parse_status_display(),
        )


@admin.register(SyncCheckpoint)
class SyncCheckpointAdmin(admin.ModelAdmin):
    list_display = (
        'integration_account',
        'resource_type',
        'mode',
        'status',
        'last_seen_remote_id',
        'last_run_at',
    )
    list_select_related = ('integration_account',)
    list_filter = ('resource_type', 'mode', 'status')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'integration_account',
        'resource_type',
        'mode',
        'status_display',
        'processed_count',
        'error_count',
        'started_at',
        'finished_at',
    )
    list_select_related = ('integration_account',)
    list_filter = ('resource_type', 'mode', 'status')
    show_full_result_count = False
    list_per_page = 50
    readonly_fields = ('started_at', 'finished_at', 'created_at', 'updated_at')

    @admin.display(description='Status')
    def status_display(self, obj):
        colours = {
            'running': 'blue',
            'completed': 'green',
            'failed': 'red',
            'cancelled': 'gray',
        }
        colour = colours.get(obj.status, 'black')
        return format_html(
            '<span style="color: {};">{}</span>',
            colour,
            obj.get_status_display(),
        )


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = (
        'created_at',
        'level_display',
        'task_name',
        'message_short',
        'integration_account',
    )
    list_select_related = ('integration_account',)
    list_filter = ('level', 'task_name', 'integration_account')
    search_fields = ('message',)
    show_full_result_count = False
    readonly_fields = (
        'task_name',
        'level',
        'message',
        'detail',
        'integration_account',
        'order',
        'listing',
        'owned_product',
        'sync_run',
        'created_at',
    )
    list_per_page = 50
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Level')
    def level_display(self, obj):
        colours = {
            'info': '#2196F3',
            'success': '#4CAF50',
            'warning': '#FF9800',
            'error': '#F44336',
        }
        colour = colours.get(obj.level, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colour,
            obj.get_level_display(),
        )

    @admin.display(description='Message')
    def message_short(self, obj):
        if len(obj.message) > 80:
            return obj.message[:80] + '...'
        return obj.message


@admin.register(SyncFeatureFlag)
class SyncFeatureFlagAdmin(admin.ModelAdmin):
    list_display = ('key', 'is_enabled', 'description', 'updated_at')
    list_editable = ('is_enabled',)
    list_display_links = ('key',)
    search_fields = ('key', 'description')
    readonly_fields = ('updated_at',)
