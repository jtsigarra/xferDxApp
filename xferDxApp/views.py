from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.views import LoginView
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.views.decorators.csrf import csrf_exempt
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.core.files.base import ContentFile
from django.utils.html import strip_tags

from weasyprint import HTML
from datetime import date

from .forms import PatientForm, DicomUploadForm, CustomLoginForm
from .models import Study, Patient, ProcedureSchedule, Attachment, Report
from .decorators import role_required

import os
import re
import threading

class CustomLoginView(LoginView):
    authentication_form = CustomLoginForm
    template_name = 'login.html'

def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def dashboard(request):
    patients = Patient.objects.all()
    schedules = ProcedureSchedule.objects.select_related('patient').order_by('date')
    studies_count = ProcedureSchedule.objects.filter(status__in=['uploaded', 'finalized']).count()
    urgent_studies = ProcedureSchedule.objects.filter(status__in=['uploaded'], studies__exam_priority__in=['urgent', 'stat']).distinct().count()
    pending_reads = ProcedureSchedule.objects.filter(status='uploaded').count()
    return render(request, 'dashboard.html', {
        'patients': patients, 
        'schedules': schedules, 
        'studies': studies_count,
        'urgent_studies': urgent_studies,
        'pending_reads': pending_reads,
    })

@role_required('radtech', 'staff', 'admin')
def patient(request):
    patients = Patient.objects.all()
    schedules = ProcedureSchedule.objects.select_related('patient').order_by('date')
    return render(request, 'patient.html', {
        'patients': patients, 
        'schedules': schedules
    })

@login_required
def telehealth(request):
    return render(request, 'telehealth.html')


def reports(request):
    patients = Patient.objects.all()
    schedules = ProcedureSchedule.objects.select_related('patient').filter(status='uploaded').order_by('-date')
    return render(request, 'reports.html', {
        'patients': patients, 
        'schedules': schedules
    })

@role_required('radtech', 'staff', 'admin')
def add_patient(request):

    if request.method == 'POST':
        form = PatientForm(request.POST)
        
        if form.is_valid():
            form.save()
            messages.success(request, 'Patient added successfully!')
            return redirect('add_patient')
        else:
            messages.error(request, 'Please correct the errors below.')
    
    else:
        form = PatientForm()
    
    context = {'form': form,}
    return render(request, 'add_patient.html', context)

def get_ph_time():
    """Get current time in Philippine timezone"""
    return timezone.now()

def download_dicom(request, dicom_id):
    dicom_image = get_object_or_404(Study, id=dicom_id)

    if dicom_image.file:
        try:
            with open(dicom_image.file.path, 'rb') as f:
                response = HttpResponse(f.read(), content_type='application/dicom')
                response['Content-Disposition'] = f'attachment; filename="{dicom_image.file_name}"'
                return response
        except Exception as e:
            messages.error(request, f'Error downloading file: {str(e)}')
            return redirect('patient_detail', patient_id=dicom_image.patient.id)
    else:
        messages.error(request, 'File not found')
        return redirect('patient_detail', patient_id=dicom_image.patient.id)
    
@login_required
def patient_detail(request, patient_id):
    patient = get_object_or_404(Patient, id=patient_id)
    studies = patient.studies.all()
    reports = Report.objects.filter(patient=patient)
    
    context = {
        'patient': patient,
        'studies': studies,
        "reports": reports,
    }
    
    return render(request, 'patient_detail.html', context)

@role_required('radtech', 'staff', 'admin')
def upload_dicom(request):
    form = DicomUploadForm(request.POST or None, request.FILES or None)
    dicom_images = Study.objects.select_related('patient', 'procedure_schedule').all()

    if request.method == 'POST':
        files = request.FILES.getlist('dicom_files')

        if form.is_valid():
            patient = form.cleaned_data['patient']
            study_schedule = form.cleaned_data['study']
            exam_priority = form.cleaned_data['exam_priority']
            clinical_history = form.cleaned_data['clinical_history']

            upload_dir = os.path.join(settings.MEDIA_ROOT, 'dicom_files', f'patient_{patient.id}')
            os.makedirs(upload_dir, exist_ok=True)

            for f in files:
                Study.objects.create(
                    patient=patient,
                    procedure_schedule=study_schedule,
                    file=f,
                    exam_priority=exam_priority,
                    clinical_history=clinical_history
                )

            study_schedule.status = 'uploaded'
            study_schedule.save()

            messages.success(
                request,
                f'Successfully uploaded {len(files)} DICOM file(s) for {study_schedule.study_id}!'
            )
            return redirect('dashboard')
        else:
            messages.error(request, 'Please correct the errors below.')

    # Get all patients for the dropdown
    patients = Patient.objects.all().order_by('last_name')

    schedules = ProcedureSchedule.objects.select_related('patient').all().order_by('-date')

    context = {
        'form': form,
        'dicom_images': dicom_images,
        'schedules': schedules,
        'patients': patients,
    }

    return render(request, 'upload_dicom.html', context)


@login_required
@csrf_exempt
def process_dicom_upload(request):
    """Process the multi-step DICOM upload from the new upload interface"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
    
    try:
        # Get form data
        patient_id = request.POST.get('patient_id')
        procedure_schedule_id = request.POST.get('procedure_schedule_id')  # ✅ corrected
        exam_priority = request.POST.get('exam_priority', 'routine')
        clinical_history = request.POST.get('clinical_history', '')
        
        # Validate and get objects
        patient = get_object_or_404(Patient, id=patient_id)
        procedure_schedule = None

        if procedure_schedule_id:  # Only fetch if provided
            procedure_schedule = get_object_or_404(ProcedureSchedule, id=procedure_schedule_id)
        
        # Get DICOM and attachments
        dicom_files = request.FILES.getlist('dicom_files')
        attachment_files = request.FILES.getlist('attachment_files')

        if not dicom_files:
            return JsonResponse({'success': False, 'message': 'No DICOM files uploaded'})
        
        # Create upload directory
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'dicom_files', f'patient_{patient.id}')
        os.makedirs(upload_dir, exist_ok=True)
        
        uploaded_studies = []
        
        # Save each DICOM file
        for dicom_file in dicom_files:
            study = Study(
                patient=patient,
                file=dicom_file,
                exam_priority=exam_priority,
                clinical_history=clinical_history,
            )

            # ✅ Only assign if schedule exists
            if procedure_schedule:
                study.procedure_schedule = procedure_schedule

            study.save()
            uploaded_studies.append(study)
        
        # ✅ Mark schedule as uploaded (if provided)
        if procedure_schedule:
            procedure_schedule.status = 'uploaded'
            procedure_schedule.save()
        
        # Process attachments if any
        if attachment_files:
            for study in uploaded_studies:
                for attachment_file in attachment_files:
                    file_ext = attachment_file.name.split('.')[-1].lower()
                    if file_ext in ['jpg', 'jpeg', 'png', 'gif']:
                        file_type = 'image'
                    elif file_ext in ['pdf', 'doc', 'docx', 'txt']:
                        file_type = 'document'
                    elif file_ext in ['mp4', 'avi', 'mov', 'wmv']:
                        file_type = 'video'
                    else:
                        file_type = 'other'
                    
                    Attachment.objects.create(
                        study=study,
                        file=attachment_file,
                        file_name=attachment_file.name,
                        file_type=file_type,
                        file_size=attachment_file.size
                    )
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully uploaded {len(dicom_files)} DICOM file(s) with {len(attachment_files)} attachment(s)',
            'study_count': len(uploaded_studies)
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})


@login_required
def radiologist_review(request):
    """NEW: Display pending studies for radiologist review"""
    pending_studies = Study.objects.filter(status='pending').select_related('patient').prefetch_related('attachments')
    return render(request, 'radiologist_review.html', {'pending_studies': pending_studies})

def send_mail_async(subject, message, recipients):
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        recipients,
        fail_silently=False,  # 👈 IMPORTANT
    )


@login_required
def schedule_procedure(request):
    patients = Patient.objects.all()
    schedules = ProcedureSchedule.objects.select_related('patient').order_by('-date', '-time')

    if request.method == 'POST':
        print("POST:", request.POST)
        patient_id = request.POST.get('patient')
        procedure = request.POST.get('procedure_type')
        date = request.POST.get('date')
        time = request.POST.get('time')
        notes = request.POST.get('special_instructions')

        if not all([patient_id, procedure, date, time]):
            messages.error(request, "Please fill in all required fields.")
            return redirect('patient')

        patient = get_object_or_404(Patient, id=patient_id)

        # --- Safe schedule creation with retry in case of duplicate study_id
        for _ in range(3):  # retry up to 3 times
            try:
                with transaction.atomic():
                    schedule = ProcedureSchedule.objects.create(
                        patient=patient,
                        procedure_type=procedure,
                        date=date,
                        time=time,
                        special_instructions=notes
                    )
                break  # success, exit loop
            except IntegrityError:
                # regenerate a new study_id (the model’s save() will handle it)
                schedule = ProcedureSchedule(patient=patient, procedure_type=procedure, date=date, time=time, special_instructions=notes)
                schedule.study_id = None
                continue
        else:
            messages.error(request, "Failed to create a unique study ID. Please try again.")
            return redirect('patient')

        # --- Email notifications ---
        subject = f"Procedure Scheduled: {procedure.title().upper()}"
        message = (
            f"Dear {patient.first_name},\n\n"
            f"Your {procedure.title().upper()} is scheduled on {date} at {time}.\n"
            f"Special Instructions: {notes or 'None'}\n\n"
            "Thank you,\nRadiology Department"
        )

        print("PATIENT EMAIL:", patient.email_address)

        if patient.email_address:
            send_mail_async(subject, message, [patient.email_address])

        return redirect('patient')

    return render(request, 'patients.html', {'patients': patients, 'schedules': schedules})

@login_required
def get_studies_for_patient(request):
    patient_id = request.GET.get('patient_id')
    studies = ProcedureSchedule.objects.filter(patient_id=patient_id)

    data = [
        {
            'id': s.id,
            'study_id': s.study_id,
            'procedure_type': s.get_procedure_type_display(),
            'date': s.date.strftime('%Y-%m-%d'),
        }
        for s in studies
    ]
    return JsonResponse({'studies': data})

@login_required
def get_patient_procedures(request, patient_id):
    schedules = ProcedureSchedule.objects.filter(patient_id=patient_id, status='scheduled').values(
        'id', 'procedure_type', 'date'
    )
    data = list(schedules)
    return JsonResponse({'procedures': data})

def clean_editor_input(html):
    if not html:
        return ""

    # Convert block and line-break tags into newlines
    html = re.sub(r'<br\s*/?>', '\n', html)
    html = re.sub(r'</div>', '\n', html)
    html = re.sub(r'<div[^>]*>', '', html)

    # Remove remaining HTML
    text = strip_tags(html)

    # Normalize excessive newlines
    return text.strip()

@role_required('radiologist')
def dicom_viewer(request, study_id):
    """Display DICOM viewer and save report for a specific study"""
    study = get_object_or_404(Study, id=study_id)
    patient = study.patient
    schedule = study.procedure_schedule

    dicom_url = request.build_absolute_uri(study.file.url)
    current_procedure_type = schedule.procedure_type

    # ✅ HANDLE REPORT SAVE
    if request.method == "POST":
        raw_findings = request.POST.get("findings", "")
        raw_impression = request.POST.get("impression", "")

        findings = clean_editor_input(raw_findings)
        impression = clean_editor_input(raw_impression)

        if findings and impression:
            # Optional: prevent duplicate report for same procedure
            report, created = Report.objects.get_or_create(
                procedure_schedule=schedule,
                defaults={
                    "patient": patient,
                    "findings": findings,
                    "impression": impression,
                    "created_by": request.user,
                }
            )

            if not created:
                # If you prefer updating instead of blocking:
                report.findings = findings
                report.impression = impression
                report.created_by = request.user
                report.save()

            schedule.status = "finalized"
            schedule.save()

            age = calculate_age(patient.date_of_birth)

            html = render_to_string(
                "reports/template.html",
                {
                    "report": report,
                    "patient": patient,
                    "procedure_schedule": schedule,
                    "age": age,
                }
            )

            pdf = HTML(string=html, base_url=settings.STATIC_ROOT).write_pdf()
            report.pdf.save(
                f"Report_{patient.patient_id}.pdf",
                ContentFile(pdf),
                save=True,
            )

            return HttpResponse(pdf, content_type="application/pdf")

    # ✅ GET MODE (viewer)
    related_studies = Study.objects.filter(procedure_schedule=schedule).select_related("procedure_schedule").order_by("-upload_time")
    attachments = study.attachments.all()

    context = {
        "study": study,
        "patient": patient,
        "dicom_url": dicom_url,
        "related_studies": related_studies,
        "current_procedure_type": current_procedure_type,
        "attachments": attachments,
    }

    return render(request, "dicom_viewer.html", context)

@login_required
@csrf_exempt
def update_study_info(request, study_id):
    """NEW: Update study information from radiologist review"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'})
    
    try:
        study = get_object_or_404(Study, id=study_id)
        
        # Update fields
        study.exam_priority = request.POST.get('exam_priority', study.exam_priority)
        study.clinical_history = request.POST.get('clinical_history', study.clinical_history)
        study.status = request.POST.get('status', study.status)
        
        # If status is changed to completed, record the reviewer and time
        if study.status == 'completed' and request.user.is_authenticated:
            study.reviewed_by = request.user.username
            study.reviewed_at = timezone.now()
        
        study.save()
        
        messages.success(request, f'Study {study.study_id} updated successfully!')
        return JsonResponse({'success': True, 'message': 'Study updated successfully'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})
    
@login_required
def get_uploaded_procedures(request):
    patient_id = request.GET.get('patient_id')

    if not patient_id:
        return JsonResponse({'procedures': []})

    # Only fetch uploaded procedures for the selected patient
    procedures = ProcedureSchedule.objects.filter(
        patient_id=patient_id,
        status='uploaded'
    ).values('id', 'procedure_type', 'date')

    return JsonResponse({'procedures': list(procedures)})

@role_required('radiologist', 'admin')
def save_report(request):
    if request.method == "POST":
        patient_id = request.POST.get("patient_id")
        schedule_id = request.POST.get("procedure_schedule_id")
        findings = request.POST.get("findings")
        impression = request.POST.get("impression")

        patient = Patient.objects.get(id=patient_id)
        schedule = ProcedureSchedule.objects.get(id=schedule_id)

        report = Report.objects.create(
            patient=patient,
            procedure_schedule=schedule,
            findings=findings,
            impression=impression,
        )

        schedule.status = "finalized"
        schedule.save()

        age = calculate_age(patient.date_of_birth)

        # Render HTML template with report data
        html_string = render_to_string('reports/template.html', {
            'report': report,
            'patient': report.patient,
            'procedure_schedule': schedule,
            'age': age,
        })

        # Convert HTML to PDF
        pdf_file = HTML(string=html_string, base_url=settings.STATIC_ROOT).write_pdf()

        report.pdf.save(f"Report_{report.patient.patient_id}.pdf",ContentFile(pdf_file),save=True)

        # Return as PDF download
        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename=Report_{report.patient.patient_id}.pdf'
        return response

    # GET: show form or list
    patients = Patient.objects.all()
    schedules = ProcedureSchedule.objects.filter(status="uploaded")
    return render(request, "reports.html", {"patients": patients, "schedules": schedules})

def calculate_age(birth_date):
    today = date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

@login_required
def no_permission(request):
    return render(request, 'forbidden.html', status=403)