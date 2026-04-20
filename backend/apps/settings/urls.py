from django.urls import path

from . import views
from apps.integrations import views as integration_views

app_name = 'settings'

urlpatterns = [
    path('groups/', views.GroupListView.as_view(), name='group_list'),
    path('groups/create/', views.GroupCreateView.as_view(), name='group_create'),
    path('groups/<int:pk>/edit/', views.GroupEditView.as_view(), name='group_edit'),
    path('groups/<int:pk>/delete/', views.GroupDeleteView.as_view(), name='group_delete'),
    path('games/', views.GameListView.as_view(), name='game_list'),

    # External services (RobuxCrate, Proxyline, etc.)
    path('services/', integration_views.ServiceListView.as_view(), name='service_list'),
    path('services/create/', integration_views.ServiceCreateView.as_view(), name='service_create'),
    path('services/api/fields/<str:service_type>/', integration_views.ServiceFieldsView.as_view(), name='service_fields'),
    path('services/<slug:slug>/', integration_views.ServiceDetailView.as_view(), name='service_detail'),
    path('services/<slug:slug>/edit/', integration_views.ServiceUpdateView.as_view(), name='service_edit'),
    path('services/<slug:slug>/delete/', integration_views.ServiceDeleteView.as_view(), name='service_delete'),
    path('services/<slug:slug>/test/', integration_views.ServiceTestView.as_view(), name='service_test'),
]
