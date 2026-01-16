from django.urls import path
from . import views

app_name = 'dms'

urlpatterns = [
    path('', views.index, name='index'),
    path('upload/', views.upload_page, name='upload_page'),
    path('upload/file/', views.upload_file, name='upload_file'),
    path('documents/', views.document_list, name='document_list'),
    path('documents/<uuid:pk>/', views.document_detail, name='document_detail'),
    path('documents/<uuid:pk>/download/', views.document_download, name='document_download'),
    path('documents/<uuid:pk>/versions/', views.document_versions, name='document_versions'),
    path('documents/<uuid:pk>/versions/<int:version_number>/download/', views.document_version_download, name='document_version_download'),
    path('tasks/', views.task_list, name='task_list'),
    path('tasks/<uuid:pk>/complete/', views.task_complete, name='task_complete'),
    path('personnel-files/', views.personnel_file_list, name='personnel_file_list'),
    path('personnel-files/<uuid:pk>/', views.personnel_file_detail, name='personnel_file_detail'),
    path('personnel-files/create/<int:employee_id>/', views.personnel_file_create, name='personnel_file_create'),
    path('personnel-files/<uuid:pk>/add-document/', views.personnel_file_add_document, name='personnel_file_add_document'),
    path('employees/', views.employee_list, name='employee_list'),
    path('filing-plan/', views.filing_plan, name='filing_plan'),
    
    # Sage Cloud Sync
    path('sage-sync/', views.sage_sync_dashboard, name='sage_sync_dashboard'),
    path('sage-sync/employees/', views.sage_sync_employees, name='sage_sync_employees'),
    path('sage-sync/leave-requests/', views.sage_sync_leave_requests, name='sage_sync_leave_requests'),
    path('sage-sync/timesheets/', views.sage_sync_timesheets, name='sage_sync_timesheets'),
]
