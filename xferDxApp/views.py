from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.utils import timezone
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
import requests
import re

from .forms import PatientForm, DicomUploadForm, CustomLoginForm
from .models import Study, Patient, ProcedureSchedule, Attachment, Report
from .decorators import role_required


# -------------------------
# AUTH
# -------------------------

class CustomLoginView(LoginView):
    authentication_form = CustomLoginForm
    template_name = "login.html"


def logout_view(request):
    logout(request)
    return redirect("login")


# -------------------------
# DASHBOARD & BASIC VIEWS
# -------------------------

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

    return render(request, "dashboard.html", {
        "patients": patients,
        "schedules": schedules,
        "studies": studies_count,
        "urgent_studies": urgent_studies,
        "pending_reads": pending_reads,
    })


@role_required("radtech", "staff", "admin")
def patient(request):
    patients = Patient.objects.all()
    schedules = ProcedureSchedule.objects.select_related("patient").order_by("date")
    return render(request, "patient.html", {
        "patients": patients,
        "schedules": schedules,
    })


@login_required
def telehealth(request):
    return render(request, "telehealth.html")


def reports(request):
    patients = Patient.objects.all()
    schedules = ProcedureSchedule.objects.select_related("patient").filter(
        status="uploaded"
    ).order_by("-date")
    return render(request, "reports.html", {
        "patients": patients,
        "schedules": schedules,
    })


# -------------------------
# PATIENT MANAGEMENT
# -------------------------

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


@login_required
def patient_detail(request, patient_id):
    patient = get_object_or_404(Patient, id=patient_id)
    studies = patient.studies.all()
    reports = Report.objects.filter(patient=patient)

    return render(request, "patient_detail.html", {
        "patient": patient,
        "studies": studies,
        "reports": reports,
    })


# -------------------------
# CLOUDINARY-SAFE DOWNLOAD
# -------------------------

@login_required
def download_dicom(request, dicom_id):
    study = get_object_or_404(Study, id=dicom_id)

    if not study.file:
        messages.error(request, "File not found")
        return redirect("patient_detail", patient_id=study.patient.id)

    try:
        r = requests.get(study.file.url, stream=True, timeout=10)
        r.raise_for_status()

        response = StreamingHttpResponse(
            r.iter_content(chunk_size=8192),
            content_type="application/dicom"
        )
        response["Content-Disposition"] = (
            f'attachment; filename="{study.file_name or "image.dcm"}"'
        )
        return response

    except requests.RequestException as e:
        messages.error(request, f"Download failed: {str(e)}")
        return redirect("patient_detail", patient_id=study.patient.id)


# -------------------------
# SIMPLE UPLOAD PAGE
# -------------------------

@role_required("radtech", "staff", "admin")
def upload_dicom(request):
    form = DicomUploadForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        patient = form.cleaned_data["patient"]
        schedule = form.cleaned_data["study"]
        exam_priority = form.cleaned_data["exam_priority"]
        clinical_history = form.cleaned_data["clinical_history"]
        files = request.FILES.getlist("dicom_files")

        for f in files:
            Study.objects.create(
                patient=patient,
                procedure_schedule=schedule,
                file=f,
                exam_priority=exam_priority,
                clinical_history=clinical_history,
            )

        schedule.status = "uploaded"
        schedule.save()

        messages.success(request, f"Uploaded {len(files)} DICOM file(s).")
        return redirect("dashboard")

    patients = Patient.objects.all().order_by("last_name")
    schedules = ProcedureSchedule.objects.select_related("patient").order_by("-date")

    return render(request, "upload_dicom.html", {
        "form": form,
        "patients": patients,
        "schedules": schedules,
    })


# -------------------------
# MULTI-STEP CLOUDINARY UPLOAD
# -------------------------

@login_required
@csrf_exempt
def process_dicom_upload(request):
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Invalid request"})

    try:
        patient = get_object_or_404(Patient, id=request.POST.get("patient_id"))
        schedule_id = request.POST.get("procedure_schedule_id")
        schedule = (
            get_object_or_404(ProcedureSchedule, id=schedule_id)
            if schedule_id else None
        )

        exam_priority = request.POST.get("exam_priority", "routine")
        clinical_history = request.POST.get("clinical_history", "")
        dicom_files = request.FILES.getlist("dicom_files")
        attachments = request.FILES.getlist("attachment_files")

        if not dicom_files:
            return JsonResponse({"success": False, "message": "No DICOM files uploaded"})

        uploaded_studies = []

        for dicom in dicom_files:
            study = Study.objects.create(
                patient=patient,
                procedure_schedule=schedule,
                file=dicom,
                exam_priority=exam_priority,
                clinical_history=clinical_history,
            )
            uploaded_studies.append(study)

        if schedule:
            schedule.status = "uploaded"
            schedule.save()

        for study in uploaded_studies:
            for file in attachments:
                ext = file.name.split(".")[-1].lower()
                if ext in ["jpg", "jpeg", "png", "gif"]:
                    file_type = "image"
                elif ext in ["pdf", "doc", "docx", "txt"]:
                    file_type = "document"
                elif ext in ["mp4", "avi", "mov", "wmv"]:
                    file_type = "video"
                else:
                    file_type = "other"

                Attachment.objects.create(
                    study=study,
                    file=file,
                    file_name=file.name,
                    file_type=file_type,
                    file_size=file.size,
                )

        return JsonResponse({"success": True, "study_count": len(uploaded_studies)})

    except Exception as e:
        return JsonResponse({"success": False, "message": str(e)})


# -------------------------
# RADIOLOGIST VIEWER
# -------------------------

def clean_editor_input(html):
    html = re.sub(r"<br\s*/?>", "\n", html or "")
    html = re.sub(r"</div>", "\n", html)
    html = re.sub(r"<div[^>]*>", "", html)
    return strip_tags(html).strip()


@role_required("radiologist")
def dicom_viewer(request, study_id):
    study = get_object_or_404(Study, id=study_id)
    patient = study.patient
    schedule = study.procedure_schedule

    dicom_url = study.file.url

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

        html = render_to_string("reports/template.html", {
            "report": report,
            "patient": patient,
            "procedure_schedule": schedule,
            "age": calculate_age(patient.date_of_birth),
        })

        pdf = HTML(string=html).write_pdf()
        report.pdf.save(
            f"Report_{patient.patient_id}.pdf",
            ContentFile(pdf),
            save=True,
        )

        return HttpResponse(pdf, content_type="application/pdf")

    return render(request, "dicom_viewer.html", {
        "study": study,
        "patient": patient,
        "dicom_url": dicom_url,
        "attachments": study.attachments.all(),
    })


# -------------------------
# UTILITIES
# -------------------------

def calculate_age(birth_date):
    today = date.today()
    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


@login_required
def no_permission(request):
    return render(request, "forbidden.html", status=403)

@login_required
def get_uploaded_procedures(request):
    patient_id = request.GET.get('patient_id')

    if not patient_id:
        return JsonResponse({'procedures': []})

    procedures = ProcedureSchedule.objects.filter(
        patient_id=patient_id,
        status='uploaded'
    ).values('id', 'procedure_type', 'date')

    return JsonResponse({'procedures': list(procedures)})
