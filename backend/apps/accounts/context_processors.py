def user_role(request):
    """Expose {{ user_role }} in templates."""
    if not request.user.is_authenticated:
        return {'user_role': None}
    if request.user.is_superuser:
        return {'user_role': 'admin'}
    return {'user_role': request.user.role}
