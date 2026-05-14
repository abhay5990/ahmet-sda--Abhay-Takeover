from django.urls import path

from . import views
from .api import stock as stock_api
from .api import dropship as dropship_api
from .api import pool as pool_api
from .api import content_templates as content_template_api
from .api import cosmetic_lists as cosmetic_list_api
from .api import manual as manual_api

app_name = 'posting'

urlpatterns = [
    # Stock UI
    path('stock/start/', views.stock_start_page, name='stock_start'),
    path('stock/active/', views.stock_active_page, name='stock_active'),
    path('stock/history/', views.stock_history_page, name='stock_history'),
    path('stock/jobs/<int:job_id>/', views.stock_job_detail, name='stock_job_detail'),
    path('templates/', views.content_templates_page, name='content_templates'),
    path('templates/editor/', views.content_template_editor_page, name='content_template_editor'),
    path('templates/editor/<int:template_id>/', views.content_template_editor_page, name='content_template_editor_edit'),
    path('templates/cosmetic-lists/', views.cosmetic_lists_page, name='cosmetic_lists'),

    # Dropship UI
    path('dropship/configs/', views.dropship_configs_page, name='dropship_configs'),
    path('dropship/items/', views.dropship_items_page, name='dropship_items'),
    path('dropship/activity/', views.dropship_activity_page, name='dropship_activity'),

    # Auto Restock UI
    path('restock/pools/', views.restock_pools_page, name='restock_pools'),
    path('restock/pools/<int:pool_id>/', views.restock_pool_detail_page, name='restock_pool_detail'),

    # API — job lifecycle
    path('api/jobs/', stock_api.create_job, name='api_create_job'),
    path('api/jobs/<int:job_id>/', stock_api.job_status, name='api_job_status'),


    # API — job actions
    path('api/jobs/<int:job_id>/cancel/', stock_api.cancel_job, name='api_cancel_job'),
    path('api/repost-data/', stock_api.repost_data, name='api_repost_data'),

    # API — defaults + stores
    path('api/defaults/<int:game_id>/<str:marketplace>/', stock_api.posting_defaults, name='api_posting_defaults'),
    path('api/stores/', stock_api.available_stores, name='api_available_stores'),

    # API — content templates
    path('api/content-templates/', content_template_api.list_content_templates, name='api_content_templates'),
    path('api/content-templates/metadata/', content_template_api.content_template_metadata, name='api_content_template_metadata'),
    path('api/content-templates/create/', content_template_api.create_content_template, name='api_create_content_template'),
    path('api/content-templates/<int:template_id>/', content_template_api.content_template_detail, name='api_content_template_detail'),
    path('api/content-templates/preview/', content_template_api.preview_content_template, name='api_preview_content_template'),

    # API — cosmetic lists
    path('api/cosmetic-lists/', cosmetic_list_api.list_cosmetic_lists, name='api_cosmetic_lists'),
    path('api/cosmetic-lists/create/', cosmetic_list_api.create_cosmetic_list, name='api_create_cosmetic_list'),
    path('api/cosmetic-lists/<int:list_id>/', cosmetic_list_api.cosmetic_list_detail, name='api_cosmetic_list_detail'),
    path('api/cosmetic-lists/reorder/', cosmetic_list_api.reorder_cosmetic_lists, name='api_reorder_cosmetic_lists'),

    # API — dropship poster control
    path('api/dropship/configs/<int:config_id>/poster/stop/', dropship_api.poster_stop, name='api_poster_stop'),
    path('api/dropship/configs/<int:config_id>/poster/resume/', dropship_api.poster_resume, name='api_poster_resume'),

    # API — dropship cleaner control (per source account)
    path('api/dropship/cleaners/', dropship_api.cleaner_configs, name='api_cleaner_configs'),
    path('api/dropship/cleaners/<int:cleaner_id>/toggle/', dropship_api.cleaner_toggle, name='api_cleaner_toggle'),
    path('api/dropship/cleaners/<int:cleaner_id>/stop/', dropship_api.cleaner_stop, name='api_cleaner_stop'),
    path('api/dropship/cleaners/<int:cleaner_id>/resume/', dropship_api.cleaner_resume, name='api_cleaner_resume'),

    # API — scheduler status + bulk
    path('api/dropship/scheduler/status/', dropship_api.scheduler_status, name='api_scheduler_status'),
    path('api/dropship/stop-all/', dropship_api.stop_all, name='api_stop_all'),

    # API — dropship configs
    path('api/dropship/configs/', dropship_api.dropship_configs, name='api_dropship_configs'),
    path('api/dropship/configs/create/', dropship_api.create_dropship_config, name='api_create_dropship_config'),
    path('api/dropship/configs/<int:config_id>/', dropship_api.update_dropship_config, name='api_update_dropship_config'),
    path('api/dropship/configs/<int:config_id>/delete/', dropship_api.delete_dropship_config, name='api_delete_dropship_config'),
    path('api/dropship/configs/<int:config_id>/urls/', dropship_api.create_dropship_url, name='api_create_dropship_url'),

    # API — dropship URLs
    path('api/dropship/urls/<int:url_id>/', dropship_api.update_dropship_url, name='api_update_dropship_url'),
    path('api/dropship/urls/<int:url_id>/delete/', dropship_api.delete_dropship_url, name='api_delete_dropship_url'),

    # API — subplatform limits
    path('api/dropship/subplatform-limits/', dropship_api.subplatform_limits, name='api_subplatform_limits'),
    path('api/dropship/subplatform-limits/save/', dropship_api.save_subplatform_limits, name='api_save_subplatform_limits'),

    # API — dropship stats
    path('api/dropship/stats/', dropship_api.dropship_stats, name='api_dropship_stats'),

    # API — dropship item actions
    path('api/dropship/items/<int:item_id>/', dropship_api.dropship_item_action, name='api_dropship_item_action'),
    path('api/dropship/items/bulk/', dropship_api.dropship_item_bulk_action, name='api_dropship_item_bulk_action'),

    # API — manual posting (Fortnite Google Sheets)
    path('api/manual/fortnite/sheet/', manual_api.open_sheet, name='api_manual_fortnite_sheet'),
    path('api/manual/fortnite/accounts/', manual_api.fetch_accounts, name='api_manual_fortnite_accounts'),

    # API — offer pools (auto restock)
    path('api/pools/', pool_api.list_pools, name='api_list_pools'),
    path('api/pools/create/', pool_api.create_pool, name='api_create_pool'),
    path('api/pools/<int:pool_id>/', pool_api.pool_detail, name='api_pool_detail'),
    path('api/pools/<int:pool_id>/update/', pool_api.update_pool, name='api_update_pool'),
    path('api/pools/<int:pool_id>/delete/', pool_api.delete_pool, name='api_delete_pool'),
    path('api/pools/<int:pool_id>/items/', pool_api.add_pool_items, name='api_add_pool_items'),
    path('api/pools/<int:pool_id>/items/<int:item_id>/remove/', pool_api.remove_pool_item, name='api_remove_pool_item'),
    path('api/pools/<int:pool_id>/replenish/', pool_api.trigger_replenish, name='api_trigger_replenish'),
    path('api/pools/accounts/', pool_api.available_accounts, name='api_pool_accounts'),
    path('api/pools/listings/', pool_api.available_listings, name='api_pool_listings'),
]
