from apps.accounts.decorators import role_required


@role_required('admin', 'user')
def robuxcrate_page(request):
    from django.shortcuts import render
    return render(request, 'tools/robuxcrate.html')
