from datetime import date
import os
import re
import threading

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.csrf import csrf_exempt

from weasyprint import HTML

from .decorators import role_required
from .forms import CustomLoginForm, DicomUploadForm, PatientForm
from .models import Attachment, Patient, ProcedureSchedule, Report, Study


# ======================
# AUTH
# ======================

class CustomLoginView(LoginView):
    authentication_form = CustomLoginForm
    template_name = "login.html"


def logout_view(request):
    logout(request)
    return redirect("login")


# ======================
# DASHBOARD & PAGES
# ======================

@login_required
def dashboard(request):
    patients = Patient.objects.all()
    schedules = ProcedureSchedule.objects.select_related("patient").order_by("date")

    studies_count = ProcedureSchedule.objects.filter(
        status__in=["uploaded", "finalized"]
    ).count()

    urgent_studies = ProcedureSchedule.objects.filter(
        status="uploaded",
        studies__exam_priority__in=["urgent", "stat"],
    ).distinct().count()

    pending_reads = ProcedureSchedule.objects.filter(status="uploaded").count()

    return render(
        request,
        "dashboard.html",
        {
            "patients": patients,
            "schedules": schedules,
            "studies": studies_count,
            "urgent_studies": urgent_studies,
            "pending_reads": pending_reads,
        },
    )


@role_required("radtech", "staff", "admin")
def patient(request):
    patients = Patient.objects.all()
    schedules = ProcedureSchedule.objects.select_related("patient").order_by("date")

    return render(
        request,
        "patient.html",
        {"patients": patients, "schedules": schedules},
    )


@login_required
def telehealth(request):
    return render(request, "telehealth.html")


def reports(request):
    patients = Patient.objects.all()
    schedules = (
        ProcedureSchedule.objects.select_related("patient")
        .filter(status="uploaded")
        .order_by("-date")
    )

    return render(
        request,
        "reports.html",
        {"patients": patients, "schedules": schedules},
    )


# ======================
# PATIENTS
# ======================

@role_required("radtech", "staff", "admin")
def add_patient(request):
    if request.method == "POST":
        form = PatientForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Patient added successfully!")
            return redirect("add_patient")
        messages.error(request, "Please correct the errors below.")
    else:
        form = PatientForm()

    return render(request, "add_patient.html", {"form": form})


def get_ph_time():
    """Get current time in Philippine timezone"""
    return timezone.now()


# ======================
# DICOM DOWNLOAD
# ======================

@login_required
def download_dicom(request, dicom_id):
    """Cloudinary-safe download using file URL"""
    study = get_object_or_404(Study, id=dicom_id)

    if not study.file:
        messages.error(request, "File not found")
        return redirect("patient_detail", patient_id=study.patient.id)

    # Cloudinary files are served via URL (no local file access)
    return redirect(study.file.url)

    try:
        with open(study.file.path, "rb") as f:
            response = HttpResponse(f.read(), content_type="application/dicom")
            response[
                "Content-Disposition"
            ] = f'attachment; filename="{study.file_name}"'
            return response
    except Exception as exc:
        messages.error(request, f"Error downloading file: {exc}")
        return redirect("patient_detail", patient_id=study.patient.id)


# ======================
# PATIENT DETAIL
# ======================

@login_required
def patient_detail(request, patient_id):
    patient = get_object_or_404(Patient, id=patient_id)

    return render(
        request,
        "patient_detail.html",
        {
            "patient": patient,
            "studies": patient.studies.all(),
            "reports": Report.objects.filter(patient=patient),
        },
    )


# ======================
# LEGACY UPLOAD (CLOUDINARY READY)
# ======================

@role_required("radtech", "staff", "admin")
def upload_dicom(request):
    """Legacy single-step upload (Cloudinary compatible)"""
    form = DicomUploadForm(request.POST or None, request.FILES or None)
    dicom_images = Study.objects.select_related("patient", "procedure_schedule")

    if request.method == "POST" and form.is_valid():
        patient = form.cleaned_data["patient"]
        study_schedule = form.cleaned_data["study"]
        exam_priority = form.cleaned_data["exam_priority"]
        clinical_history = form.cleaned_data["clinical_history"]
        files = request.FILES.getlist("dicom_files")

        for f in files:
            Study.objects.create(
                patient=patient,
                procedure_schedule=study_schedule,
                file=f,  # CloudinaryField handles upload
                exam_priority=exam_priority,
                clinical_history=clinical_history,
            )

        study_schedule.status = "uploaded"
        study_schedule.save()

        messages.success(
            request,
            f"Successfully uploaded {len(files)} DICOM file(s)!",
        )
        return redirect("dashboard")

    patients = Patient.objects.all().order_by("last_name")
    schedules = ProcedureSchedule.objects.select_related("patient").order_by("-date")

    return render(
        request,
        "upload_dicom.html",
        {
            "form": form,
            "dicom_images": dicom_images,
            "schedules": schedules,
            "patients": patients,
        },
    )


# ======================
# NEW MULTI-STEP UPLOAD (CLOUDINARY)
# ======================

# ======================

@login_required
@csrf_exempt
def process_dicom_upload(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Invalid request method"})

    try:
        patient = get_object_or_404(Patient, id=request.POST.get("patient_id"))
        schedule_id = request.POST.get("procedure_schedule_id")
        procedure_schedule = (
            get_object_or_404(ProcedureSchedule, id=schedule_id)
            if schedule_id
            else None
        )

        dicom_files = request.FILES.getlist("dicom_files")
        attachment_files = request.FILES.getlist("attachment_files")

        if not dicom_files:
            return JsonResponse({"success": False, "message": "No DICOM files uploaded"})

        uploaded_studies = []

        for dicom_file in dicom_files:
            study = Study.objects.create(
                patient=patient,
                procedure_schedule=procedure_schedule,
                file=dicom_file,
                exam_priority=request.POST.get("exam_priority", "routine"),
                clinical_history=request.POST.get("clinical_history", ""),
            )
            uploaded_studies.append(study)

        if procedure_schedule:
            procedure_schedule.status = "uploaded"
            procedure_schedule.save()

        for study in uploaded_studies:
            for attachment in attachment_files:
                Attachment.objects.create(
                    study=study,
                    file=attachment,
                    file_name=attachment.name,
                    file_size=attachment.size,
                )

        return JsonResponse(
            {
                "success": True,
                "study_count": len(uploaded_studies),
            }
        )

    except Exception as exc:
        return JsonResponse({"success": False, "message": str(exc)})


# ======================
# RADIOLOGIST
# ======================

@role_required("radiologist")
def dicom_viewer(request, study_id):
    study = get_object_or_404(Study, id=study_id)
    patient = study.patient
    schedule = study.procedure_schedule

    dicom_url = request.build_absolute_uri(study.file.url)

    if request.method == "POST":
        findings = clean_editor_input(request.POST.get("findings", ""))
        impression = clean_editor_input(request.POST.get("impression", ""))

        report, _ = Report.objects.update_or_create(
            procedure_schedule=schedule,
            defaults={
                "patient": patient,
                "findings": findings,
                "impression": impression,
                "created_by": request.user,
            },
        )

        schedule.status = "finalized"
        schedule.save()

        html = render_to_string(
            "reports/template.html",
            {
                "report": report,
                "patient": patient,
                "procedure_schedule": schedule,
                "age": calculate_age(patient.date_of_birth),
            },
        )

        pdf = HTML(string=html, base_url=settings.STATIC_ROOT).write_pdf()
        report.pdf.save(
            f"Report_{patient.patient_id}.pdf",
            ContentFile(pdf),
            save=True,
        )

        return HttpResponse(pdf, content_type="application/pdf")

    return render(
        request,
        "dicom_viewer.html",
        {
            "study": study,
            "patient": patient,
            "dicom_url": dicom_url,
            "attachments": study.attachments.all(),
        },
    )


# ======================
# HELPERS
# ======================

def clean_editor_input(html):
    if not html:
        return ""

    html = re.sub(r"<br\s*/?>", "\n", html)
    html = re.sub(r"</div>", "\n", html)
    html = re.sub(r"<div[^>]*>", "", html)

    return strip_tags(html).strip()


def calculate_age(birth_date):
    today = date.today()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )