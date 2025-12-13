from django import forms
from .models import Patient, ProcedureSchedule, Report
from django.contrib.auth.forms import AuthenticationForm

class CustomLoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password'
        })
    )

# Form for adding new patients
class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient  
        fields = [
            'first_name',
            'middle_name', 
            'last_name',
            'date_of_birth',
            'gender',
            'phone_number',
            'email_address',
            'emergency_contact',
            'emergency_contact_number',
            'physician_name',
            'physician_email',
            'physician_phone',
            'payment_mode',
        ]
        
        # Widgets - customize how form fields look in HTML
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter first name'
            }),
            'middle_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter middle name (optional)'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter last name'
            }),
            'date_of_birth': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'gender': forms.Select(attrs={
                'class': 'form-control'
            }),
            'phone_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 09123456789'
            }),
            'email_address': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'patient@example.com'
            }),
            'emergency_contact': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Emergency contact name'
            }),
            'emergency_contact_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 09123456789'
            }),
            'physician_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': "Enter physician's name"
            }),
            'physician_email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'doctor@example.com'
            }),
            'physician_phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': "Physician's phone number"
            }),
            'payment_mode': forms.Select(attrs={
                'class': 'form-control'
            }),
        }
        
        labels = {
            'date_of_birth': 'Date of Birth',
            'gender': 'Gender',
            'physician_name': 'Primary Physician Name',
            'physician_email': 'Physician Email',
            'physician_phone': 'Physician Phone Number',
            'payment_mode': 'Payment Mode',
        }

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = single_file_clean(data, initial)
        return result
    
class DicomUploadForm(forms.Form):
    patient = forms.ModelChoiceField(
        queryset=Patient.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Select Patient"
    )

    study = forms.ModelChoiceField(
        queryset=ProcedureSchedule.objects.none(),  # initially empty
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Select Study"
    )

    exam_priority = forms.ChoiceField(
        choices=[('routine', 'Routine'), ('urgent', 'Urgent'), ('stat', 'Stat')],
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Exam Priority"
    )

    clinical_history = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Enter clinical history and notes...'}),
        label="Clinical History"
    )

    dicom_files = MultipleFileField(
        widget=MultipleFileInput(attrs={'class': 'form-control'}),
        help_text="Select one or more DICOM files",
        label="DICOM Files"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Dynamically populate the "study" field based on selected patient
        if 'patient' in self.data:
            try:
                patient_id = int(self.data.get('patient'))
                self.fields['study'].queryset = ProcedureSchedule.objects.filter(patient_id=patient_id).order_by('-date')
            except (ValueError, TypeError):
                self.fields['study'].queryset = ProcedureSchedule.objects.none()
        elif self.initial.get('patient'):
            patient = self.initial.get('patient')
            self.fields['study'].queryset = ProcedureSchedule.objects.filter(patient=patient).order_by('-date')

class ProcedureScheduleForm(forms.ModelForm):
    class Meta:
        model = ProcedureSchedule
        fields = ['patient', 'procedure_type', 'date', 'time', 'special_instructions']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['patient'].queryset = Patient.objects.all()
        self.fields['patient'].label_from_instance = lambda obj: f"{obj.first_name} {obj.last_name}"

class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ['patient', 'procedure_schedule', 'findings', 'impression']
        widgets = {
            'patient': forms.Select(attrs={'class': 'form-control'}),
            'procedure_schedule': forms.Select(attrs={'class': 'form-control'}),
            'findings': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'impression': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
