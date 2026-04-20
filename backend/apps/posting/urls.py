from django.urls import path

from . import views
from .api import stock as stock_api
from .api import dropship as dropship_api

app_name = 'posting'

urlpatterns = [
    # Stock UI
    path('stock/start/', views.stock_start_page, name='stock_start'),
    path('stock/active/', views.stock_active_page, name='stock_active'),
    path('stock/history/', views.stock_history_page, name='stock_history'),
    path('stock/jobs/<int:job_id>/', views.stock_job_detail, name='stock_job_detail'),

    # Dropship UI
    path('dropship/configs/', views.dropship_configs_page, name='dropship_configs'),
    path('dropship/items/', views.dropship_items_page, name='dropship_items'),
    path('dropship/activity/', views.dropship_activity_page, name='dropship_activity'),

    # API — job lifecycle
    path('api/jobs/', stock_api.create_job, name='api_create_job'),
    path('api/jobs/<int:job_id>/', stock_api.job_status, name='api_job_status'),
    path('api/jobs/<int:job_id>/stream/', stock_api.job_stream, name='api_job_stream'),

    # API — job actions
    path('api/jobs/<int:job_id>/cancel/', stock_api.cancel_job, name='api_cancel_job'),
    path('api/repost-data/', stock_api.repost_data, name='api_repost_data'),

    # API — defaults + stores
    path('api/defaults/<int:game_id>/<str:marketplace>/', stock_api.posting_defaults, name='api_posting_defaults'),
    path('api/stores/', stock_api.available_stores, name='api_available_stores'),

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
]
