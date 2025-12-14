from django.db import models
from django.contrib.auth.models import AbstractUser
import os
import uuid

def dicom_upload_path(instance, filename):
    """Generate upload path for DICOM files"""
    ext = filename.split('.')[-1]
    unique_filename = f"{uuid.uuid4().hex[:16]}.{ext}"
    return os.path.join('dicom_files', f'patient_{instance.patient.id}', unique_filename)

def attachment_upload_path(instance, filename):
    """Generate upload path for attachment files"""
    return os.path.join('attachments', f'study_{instance.study.id}', filename)


class User(AbstractUser):
    ROLE_CHOICES = [
        ('staff', 'Administrative Staff'),
        ('radiologist', 'Radiologist'),
        ('radtech', 'Radiologic Technologist'),
        ('admin', 'Administrator')
    ]
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='radtech')

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
    
class Patient(models.Model):
    PAYMENT_CHOICES = [
        ('cash', 'Cash'),
        ('philhealth', 'PhilHealth'),
        ('hmo', 'HMO'),
    ]

    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other'),
    ]

    patient_id = models.CharField(max_length=10, unique=True, editable=False)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, default='O')
    phone_number = models.CharField(max_length=20)
    email_address = models.EmailField()
    emergency_contact = models.CharField(max_length=20)
    emergency_contact_number = models.CharField(max_length=20)

    physician_name = models.CharField(max_length=200)
    physician_email = models.EmailField()
    physician_phone = models.CharField(max_length=20)

    payment_mode = models.CharField(max_length=20, choices=PAYMENT_CHOICES)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.patient_id:
            last_patient = Patient.objects.order_by('-id').first()
            if last_patient:
                last_id = int(last_patient.patient_id.split('-')[1])
                new_id = last_id + 1
            else:
                new_id = 1
            self.patient_id = f"PAT-{new_id:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.last_name}, {self.first_name} "

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Patient'
        verbose_name_plural = 'Patients'


class Study(models.Model):
    patient = models.ForeignKey('Patient', on_delete=models.CASCADE, related_name='studies')
    procedure_schedule = models.ForeignKey('ProcedureSchedule', on_delete=models.CASCADE, related_name='studies')

    file = models.FileField(upload_to=dicom_upload_path)
    exam_priority = models.CharField(max_length=50, choices=[
        ('routine', 'Routine'),
        ('urgent', 'Urgent'),
        ('stat', 'Stat'),
    ], default='routine')
    clinical_history = models.TextField(blank=True)
    upload_time = models.DateTimeField(auto_now_add=True)
    metadata_extracted = models.BooleanField(default=False)
    metadata = models.JSONField(blank=True, null=True)

    file_size = models.BigIntegerField(blank=True, null=True, help_text="File size in bytes")
    file_name = models.CharField(max_length=255, blank=True)

    reviewed_by = models.CharField(max_length=200, blank=True, null=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if self.file:
            self.file_name = self.file.name
            try:
                self.file_size = self.file.size
            except (ValueError, OSError):
                self.file_size = 0

        super().save(*args, **kwargs)

        if self.procedure_schedule.status != 'uploaded':
            self.procedure_schedule.status = 'uploaded'
            self.procedure_schedule.save()


    def __str__(self):
        return f"Study #{self.pk}"

    class Meta:
        ordering = ['-upload_time']
        verbose_name = 'Study'
        verbose_name_plural = 'Studies'

class Attachment(models.Model):
    """NEW: Supporting files attached to a Study (lab results, previous reports, etc.)"""
    study = models.ForeignKey(Study, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to=attachment_upload_path)
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50)  # image, document, video
    file_size = models.BigIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Attachment #{self.pk}"
    
    class Meta:
        ordering = ['-uploaded_at']

class ProcedureSchedule(models.Model):
    PROCEDURE_CHOICES = [
        ('xray', 'X-Ray'),
        ('ct', 'CT Scan'),
        ('mri', 'MRI'),
        ('ultrasound', 'Ultrasound'),
        ('mammography', 'Mammography'),
    ]

    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('uploaded', 'DICOM Uploaded'),
        ('finalized', 'Finalized'),
    ]

    patient = models.ForeignKey('Patient', on_delete=models.CASCADE, related_name='schedules')
    procedure_type = models.CharField(max_length=50, choices=PROCEDURE_CHOICES)
    study_id = models.CharField(max_length=100, unique=True, blank=True)
    date = models.DateField()
    time = models.TimeField()
    special_instructions = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.study_id:
            initials = (
                (self.patient.first_name[:1] or '').upper() +
                (self.patient.middle_name[:1] or '').upper() +
                (self.patient.last_name[:1] or '').upper()
            ).strip() or 'PAT'

            count = ProcedureSchedule.objects.filter(patient=self.patient).count() + 1
            self.study_id = f"{initials}-{count:04d}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.study_id} - {self.patient.first_name} ({self.procedure_type}) on {self.date}"

class Report(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='reports')
    procedure_schedule = models.ForeignKey(ProcedureSchedule, on_delete=models.CASCADE, related_name='reports')

    findings = models.TextField(blank=True)
    impression = models.TextField(blank=True)
    pdf = models.FileField(upload_to='reports/', null=True, blank=True)
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Report for {self.patient.first_name}"