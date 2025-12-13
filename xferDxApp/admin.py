from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from .models import Patient, Study, ProcedureSchedule, User, Attachment

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Role Information', {'fields': ('role',)}),
    )
    list_display = ('username', 'email', 'role', 'is_staff', 'is_active')

@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ['patient_id', 'first_name', 'last_name', 'date_of_birth', 'email_address', 'created_at']
    list_filter = ['payment_mode', 'created_at']
    search_fields = ['patient_id', 'first_name', 'last_name', 'email_address']
    readonly_fields = ['patient_id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Patient Information', {
            'fields': ('patient_id', 'first_name', 'middle_name', 'last_name', 'date_of_birth')
        }),
        ('Contact Information', {
            'fields': ('phone_number', 'email_address', 'emergency_contact')
        }),
        ('Physician Information', {
            'fields': ('physician_name', 'physician_email', 'physician_phone')
        }),
        ('Payment', {
            'fields': ('payment_mode',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    readonly_fields = ['file_name', 'file_type', 'file_size', 'uploaded_at']
    fields = ['file', 'file_name', 'file_type', 'file_size', 'uploaded_at']

@admin.register(Study)
class StudyAdmin(admin.ModelAdmin):
    list_display = ['patient', 'exam_priority', 'get_status', 'upload_time', 'reviewed_by']
    list_filter = ['exam_priority', 'upload_time', 'metadata_extracted']
    search_fields = ['study_id', 'patient__first_name', 'patient__last_name', 'patient__patient_id']
    readonly_fields = ['upload_time', 'file_name', 'file_size']
    inlines = [AttachmentInline]

    fieldsets = (
        ('Study Information', {
            'fields': ('study_id', 'patient', 'file', 'file_name', 'file_size')
        }),
        ('Exam Details', {
            'fields': ('exam_priority', 'status', 'clinical_history')
        }),
        ('Metadata', {
            'fields': ('metadata_extracted', 'metadata'),
            'classes': ('collapse',)
        }),
        ('Review Information', {
            'fields': ('reviewed_by', 'reviewed_at'),
        }),
        ('Timestamps', {
            'fields': ('upload_time',),
            'classes': ('collapse',)
        }),
    )

    def get_study_id(self, obj):
        return obj.procedure_schedule.study_id
    get_study_id.short_description = 'Study ID'

    def download_link(self, obj):
        if obj.file:
            return format_html('<a href="{}" download>Download</a>', obj.file.url)
        return "No file"
    download_link.short_description = "Download File"

    def get_readonly_fields(self, request, obj=None):
        # Make reviewed_at readonly always
        readonly = list(self.readonly_fields)
        if obj and obj.reviewed_at:
            readonly.append('reviewed_at')
        return readonly
    
    def get_status(self, obj):
        return obj.procedure_schedule.get_status_display()

@admin.register(ProcedureSchedule)
class ProcedureScheduleAdmin(admin.ModelAdmin):
    list_display = ['patient', 'procedure_type', 'date', 'time', 'created_at']
    list_filter = ['procedure_type', 'date', 'created_at']
    search_fields = ['patient__first_name', 'patient__last_name', 'patient__patient_id']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Schedule Information', {
            'fields': ('patient', 'procedure_type', 'date', 'time')
        }),
        ('Additional Details', {
            'fields': ('special_instructions',)
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
