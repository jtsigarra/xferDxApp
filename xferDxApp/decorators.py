from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps

def role_required(*allowed_roles):
    """
    Restrict access to users whose role matches one of allowed_roles.
    Example: @role_required('admin', 'radiologist')
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Check if logged in
            if not request.user.is_authenticated:
                messages.error(request, "Please log in first.")
                return redirect('login')

            # Debugging: print role to confirm it exists
            print("Current user role:", request.user.role)

            # Role restriction check
            if request.user.role not in allowed_roles:
                messages.error(request, "You don’t have permission to access this page.")
                return redirect('dashboard')  # Redirect unauthorized users

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
