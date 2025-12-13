from django.urls import path
from . import views
from .views import CustomLoginView
from django.conf import settings
from django.conf.urls.static import static
from xferDxApp.views import create_superuser, run_migrations

urlpatterns = [
    path('run-migrations/', run_migrations),
    path('create-superuser/', create_superuser),
    path('', CustomLoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),

    path('dashboard/', views.dashboard, name='dashboard'),
    path('patient/', views.patient, name='patient'),
    path('telehealth/', views.telehealth, name='telehealth'),

    # Reports
    path('reports/', views.save_report, name='reports'),
    path('get-uploaded-procedures/', views.get_uploaded_procedures, name='get_uploaded_procedures'),

    # Patients
    path('add_patient/', views.add_patient, name='add_patient'),
    path('patient/<int:patient_id>/', views.patient_detail, name='patient_detail'),

    # DICOM Upload
    path('upload_dicom/', views.upload_dicom, name='upload_dicom'),
    path('process_dicom_upload/', views.process_dicom_upload, name='process_dicom_upload'),
    path('download_dicom/<int:dicom_id>/', views.download_dicom, name='download_dicom'),

    # Procedures
    path('schedule/', views.schedule_procedure, name='schedule_procedure'),
    path('get-studies/', views.get_studies_for_patient, name='get_studies'),
    path('get-procedures/<int:patient_id>/', views.get_patient_procedures, name='get_patient_procedures'),

    # Radiologist Review
    path('radiologist-review/', views.radiologist_review, name='radiologist_review'),
    path('update-study/<int:study_id>/', views.update_study_info, name='update_study_info'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
