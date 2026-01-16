import json
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q

from .models import (
    Document, Employee, Task, PersonnelFile, PersonnelFileEntry,
    FileCategory, DocumentVersion, AuditLog
)
from .encryption import encrypt_data, decrypt_data, calculate_sha256
import magic


@login_required
def index(request):
    recent_documents = Document.objects.all()[:10]
    open_tasks = Task.objects.filter(status='OPEN')[:5]
    
    stats = {
        'total_documents': Document.objects.count(),
        'unassigned': Document.objects.filter(status='UNASSIGNED').count(),
        'review_needed': Document.objects.filter(status='REVIEW_NEEDED').count(),
        'open_tasks': Task.objects.filter(status='OPEN').count(),
    }
    
    return render(request, 'dms/index.html', {
        'recent_documents': recent_documents,
        'open_tasks': open_tasks,
        'stats': stats,
    })


@login_required
def upload_page(request):
    return render(request, 'dms/upload.html')


def _check_permission(user, target_type, target_obj, required_level='VIEW'):
    from .models import AccessPermission
    from django.utils import timezone
    from django.db.models import Q
    
    if user.has_perm('dms.manage_documents'):
        return True
    if user.has_perm('dms.view_all_documents') and required_level == 'VIEW':
        return True
    
    today = timezone.now().date()
    
    permission_hierarchy = {'VIEW': 1, 'EDIT': 2, 'DELETE': 3, 'ADMIN': 4}
    required_value = permission_hierarchy.get(required_level, 1)
    
    user_groups = user.groups.all()
    
    filters = Q(user=user) | Q(group__in=user_groups)
    filters &= Q(target_type=target_type)
    filters &= (Q(valid_from__isnull=True) | Q(valid_from__lte=today))
    filters &= (Q(valid_until__isnull=True) | Q(valid_until__gte=today))
    
    if target_type == 'PERSONNEL_FILE':
        filters &= Q(personnel_file=target_obj)
    elif target_type == 'CATEGORY':
        category_ids = [target_obj.id]
        parent = target_obj.parent
        while parent:
            category_ids.append(parent.id)
            parent = parent.parent
        filters &= Q(category_id__in=category_ids)
    elif target_type == 'DEPARTMENT':
        filters &= Q(department=target_obj)
    
    perms = AccessPermission.objects.filter(filters)
    
    for perm in perms:
        perm_value = permission_hierarchy.get(perm.permission_level, 0)
        if perm_value >= required_value:
            return True
    
    return False


def _can_access_document(user, document):
    if user.has_perm('dms.view_all_documents'):
        return True
    if document.owner == user:
        return True
    if hasattr(user, 'employee_profile') and document.employee == user.employee_profile:
        return True
    
    if document.employee and hasattr(document.employee, 'personnel_file'):
        if _check_permission(user, 'PERSONNEL_FILE', document.employee.personnel_file, 'VIEW'):
            return True
    
    return False


@login_required
@csrf_protect
@require_http_methods(["POST"])
def upload_file(request):
    if 'file' not in request.FILES:
        return JsonResponse({'success': False, 'error': 'No file provided'}, status=400)
    
    uploaded_file = request.FILES['file']
    
    max_size = 50 * 1024 * 1024
    if uploaded_file.size > max_size:
        return JsonResponse({'success': False, 'error': 'File too large (max 50MB)'}, status=400)
    
    allowed_extensions = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.jpg', '.jpeg', '.png', '.tiff', '.txt'}
    file_ext = '.' + uploaded_file.name.rsplit('.', 1)[-1].lower() if '.' in uploaded_file.name else ''
    if file_ext not in allowed_extensions:
        return JsonResponse({'success': False, 'error': 'File type not allowed'}, status=400)
    
    try:
        content = uploaded_file.read()
        file_hash = calculate_sha256(content)
        encrypted_content = encrypt_data(content)
        
        try:
            mime_type = magic.from_buffer(content, mime=True)
        except Exception:
            mime_type = uploaded_file.content_type or 'application/octet-stream'
        
        title = request.POST.get('title', uploaded_file.name.rsplit('.', 1)[0])
        
        document = Document.objects.create(
            title=title,
            original_filename=uploaded_file.name,
            file_extension=file_ext,
            mime_type=mime_type,
            encrypted_content=encrypted_content,
            file_size=len(content),
            status='UNASSIGNED',
            source='WEB',
            sha256_hash=file_hash,
            owner=request.user,
        )
        
        _log_audit(request, 'CREATE', document=document, details={'filename': uploaded_file.name, 'size': len(content)})
        
        return JsonResponse({
            'success': True,
            'document_id': str(document.id),
            'message': 'File uploaded successfully'
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'Upload failed. Please try again.'}, status=500)


@login_required
def document_list(request):
    if request.user.has_perm('dms.view_all_documents'):
        documents = Document.objects.all()
    else:
        from .models import AccessPermission
        from django.utils import timezone
        
        today = timezone.now().date()
        user_groups = request.user.groups.all()
        
        perm_filter = Q(user=request.user) | Q(group__in=user_groups)
        perm_filter &= (Q(valid_from__isnull=True) | Q(valid_from__lte=today))
        perm_filter &= (Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        
        allowed_file_ids = AccessPermission.objects.filter(
            perm_filter & Q(target_type='PERSONNEL_FILE')
        ).values_list('personnel_file__employee_id', flat=True)
        
        documents = Document.objects.filter(
            Q(owner=request.user) |
            Q(employee__id__in=allowed_file_ids)
        )
        
        if hasattr(request.user, 'employee_profile'):
            documents = documents | Document.objects.filter(employee=request.user.employee_profile)
    
    status = request.GET.get('status')
    source = request.GET.get('source')
    search = request.GET.get('search')
    
    if status:
        documents = documents.filter(status=status)
    if source:
        documents = documents.filter(source=source)
    if search:
        documents = documents.filter(
            Q(title__icontains=search) | 
            Q(original_filename__icontains=search)
        )
    
    paginator = Paginator(documents, 25)
    page = request.GET.get('page', 1)
    documents = paginator.get_page(page)
    
    return render(request, 'dms/document_list.html', {
        'documents': documents,
        'status_choices': Document.STATUS_CHOICES,
        'source_choices': Document.SOURCE_CHOICES,
    })


@login_required
def document_detail(request, pk):
    document = get_object_or_404(Document, pk=pk)
    
    if not _can_access_document(request.user, document):
        return HttpResponse('Permission denied', status=403)
    
    _log_audit(request, 'VIEW', document=document)
    
    return render(request, 'dms/document_detail.html', {'document': document})


@login_required
def document_download(request, pk):
    document = get_object_or_404(Document, pk=pk)
    
    if not _can_access_document(request.user, document):
        return HttpResponse('Permission denied', status=403)
    
    try:
        decrypted_content = decrypt_data(document.encrypted_content)
        
        _log_audit(request, 'DOWNLOAD', document=document)
        
        response = HttpResponse(
            decrypted_content,
            content_type=document.mime_type or 'application/octet-stream'
        )
        response['Content-Disposition'] = f'attachment; filename="{document.original_filename}"'
        return response
    except Exception as e:
        return HttpResponse('Error downloading file', status=500)


@login_required
def task_list(request):
    if request.user.has_perm('dms.manage_documents'):
        tasks = Task.objects.all()
    else:
        tasks = Task.objects.filter(assigned_to=request.user)
    
    status = request.GET.get('status')
    if status:
        tasks = tasks.filter(status=status)
    
    paginator = Paginator(tasks, 25)
    page = request.GET.get('page', 1)
    tasks = paginator.get_page(page)
    
    return render(request, 'dms/task_list.html', {
        'tasks': tasks,
        'status_choices': Task.STATUS_CHOICES,
    })


@login_required
@require_http_methods(["POST"])
def task_complete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    
    if not request.user.has_perm('dms.manage_documents'):
        if task.assigned_to != request.user:
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)
    
    task.complete()
    
    _log_audit(
        request, 
        'EDIT', 
        document=task.document,
        details={'task_id': str(task.id), 'action': 'task_completed', 'task_title': task.title}
    )
    
    return JsonResponse({'success': True, 'message': 'Task completed'})


def _log_audit(request, action, document=None, personnel_file=None, details=None, old_value='', new_value=''):
    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
    if ',' in ip:
        ip = ip.split(',')[0].strip()
    
    AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        ip_address=ip or None,
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
        action=action,
        document=document,
        personnel_file=personnel_file,
        details=details or {},
        old_value=old_value,
        new_value=new_value,
    )


@login_required
def personnel_file_list(request):
    if request.user.has_perm('dms.view_all_documents'):
        personnel_files = PersonnelFile.objects.select_related('employee').all()
    else:
        from .models import AccessPermission
        from django.utils import timezone
        from django.db.models import Q
        
        today = timezone.now().date()
        user_groups = request.user.groups.all()
        
        perm_filter = Q(user=request.user) | Q(group__in=user_groups)
        perm_filter &= Q(target_type='PERSONNEL_FILE')
        perm_filter &= (Q(valid_from__isnull=True) | Q(valid_from__lte=today))
        perm_filter &= (Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        
        allowed_file_ids = AccessPermission.objects.filter(perm_filter).values_list('personnel_file_id', flat=True)
        
        personnel_files = PersonnelFile.objects.select_related('employee').filter(id__in=allowed_file_ids)
    
    status = request.GET.get('status')
    search = request.GET.get('search')
    
    if status:
        personnel_files = personnel_files.filter(status=status)
    if search:
        personnel_files = personnel_files.filter(
            Q(file_number__icontains=search) |
            Q(employee__first_name__icontains=search) |
            Q(employee__last_name__icontains=search) |
            Q(employee__employee_id__icontains=search)
        )
    
    paginator = Paginator(personnel_files, 25)
    page = request.GET.get('page', 1)
    personnel_files = paginator.get_page(page)
    
    return render(request, 'dms/personnel_file_list.html', {
        'personnel_files': personnel_files,
        'status_choices': PersonnelFile.STATUS_CHOICES,
    })


@login_required
def personnel_file_detail(request, pk):
    personnel_file = get_object_or_404(
        PersonnelFile.objects.select_related('employee'),
        pk=pk
    )
    
    if not request.user.has_perm('dms.view_all_documents'):
        if not _check_permission(request.user, 'PERSONNEL_FILE', personnel_file, 'VIEW'):
            return HttpResponse('Zugriff verweigert', status=403)
    
    _log_audit(request, 'VIEW', personnel_file=personnel_file)
    
    categories = FileCategory.objects.filter(parent__isnull=True).prefetch_related('subcategories')
    
    entries_by_category = {}
    for entry in personnel_file.file_entries.select_related('document', 'category').all():
        cat_code = entry.category.code.split('.')[0]
        if cat_code not in entries_by_category:
            entries_by_category[cat_code] = []
        entries_by_category[cat_code].append(entry)
    
    unassigned_documents = Document.objects.filter(status='UNASSIGNED').order_by('-created_at')[:50]
    
    return render(request, 'dms/personnel_file_detail.html', {
        'personnel_file': personnel_file,
        'categories': categories,
        'entries_by_category': entries_by_category,
        'unassigned_documents': unassigned_documents,
    })


@login_required
def personnel_file_create(request, employee_id):
    if not request.user.has_perm('dms.manage_documents'):
        return HttpResponse('Zugriff verweigert', status=403)
    
    employee = get_object_or_404(Employee, pk=employee_id)
    
    if hasattr(employee, 'personnel_file'):
        messages.warning(request, f'Personalakte für {employee.full_name} existiert bereits.')
        return redirect('dms:personnel_file_detail', pk=employee.personnel_file.pk)
    
    file_number = f"PA-{employee.employee_id}"
    
    personnel_file = PersonnelFile.objects.create(
        employee=employee,
        file_number=file_number,
        status='ACTIVE',
    )
    
    _log_audit(request, 'CREATE', personnel_file=personnel_file, details={'file_number': file_number})
    
    messages.success(request, f'Personalakte {file_number} wurde angelegt.')
    return redirect('dms:personnel_file_detail', pk=personnel_file.pk)


@login_required
@csrf_protect
@require_http_methods(["POST"])
def personnel_file_add_document(request, pk):
    if not request.user.has_perm('dms.manage_documents'):
        return JsonResponse({'success': False, 'error': 'Zugriff verweigert'}, status=403)
    
    personnel_file = get_object_or_404(PersonnelFile, pk=pk)
    
    document_id = request.POST.get('document_id')
    category_id = request.POST.get('category_id')
    document_date = request.POST.get('document_date')
    notes = request.POST.get('notes', '')
    
    if not document_id or not category_id:
        return JsonResponse({'success': False, 'error': 'Dokument und Kategorie erforderlich'}, status=400)
    
    try:
        document = Document.objects.get(pk=document_id)
        category = FileCategory.objects.get(pk=category_id)
    except (Document.DoesNotExist, FileCategory.DoesNotExist):
        return JsonResponse({'success': False, 'error': 'Dokument oder Kategorie nicht gefunden'}, status=404)
    
    entry = PersonnelFileEntry.objects.create(
        personnel_file=personnel_file,
        document=document,
        category=category,
        document_date=document_date if document_date else None,
        notes=notes,
        created_by=request.user,
    )
    
    document.status = 'ASSIGNED'
    document.employee = personnel_file.employee
    document.save()
    
    _log_audit(
        request, 
        'CREATE', 
        document=document, 
        personnel_file=personnel_file,
        details={'category': category.code, 'entry_number': entry.entry_number}
    )
    
    return JsonResponse({
        'success': True,
        'entry_id': str(entry.id),
        'entry_number': entry.entry_number,
    })


@login_required
def filing_plan(request):
    categories = FileCategory.objects.filter(parent__isnull=True).prefetch_related('subcategories')
    
    return render(request, 'dms/filing_plan.html', {
        'categories': categories,
    })


@login_required
def employee_list(request):
    if request.user.has_perm('dms.view_all_documents'):
        employees = Employee.objects.select_related('department', 'cost_center').all()
    else:
        employees = Employee.objects.none()
    
    search = request.GET.get('search')
    has_file = request.GET.get('has_file')
    
    if search:
        employees = employees.filter(
            Q(employee_id__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search)
        )
    
    if has_file == 'yes':
        employees = employees.filter(personnel_file__isnull=False)
    elif has_file == 'no':
        employees = employees.filter(personnel_file__isnull=True)
    
    for emp in employees:
        emp.has_personnel_file = hasattr(emp, 'personnel_file')
    
    paginator = Paginator(employees, 25)
    page = request.GET.get('page', 1)
    employees = paginator.get_page(page)
    
    return render(request, 'dms/employee_list.html', {
        'employees': employees,
    })


@login_required
def document_versions(request, pk):
    document = get_object_or_404(Document, pk=pk)
    
    if not _can_access_document(request.user, document):
        return HttpResponse('Zugriff verweigert', status=403)
    
    _log_audit(request, 'VIEW', document=document, details={'view': 'versions'})
    
    versions = document.versions.select_related('created_by').all()
    
    return render(request, 'dms/document_versions.html', {
        'document': document,
        'versions': versions,
    })


@login_required
def document_version_download(request, pk, version_number):
    document = get_object_or_404(Document, pk=pk)
    
    if not _can_access_document(request.user, document):
        return HttpResponse('Zugriff verweigert', status=403)
    
    version = get_object_or_404(DocumentVersion, document=document, version_number=version_number)
    
    try:
        decrypted_content = decrypt_data(version.encrypted_content)
        
        _log_audit(
            request, 
            'DOWNLOAD', 
            document=document,
            details={'version': version_number}
        )
        
        response = HttpResponse(
            decrypted_content,
            content_type=document.mime_type or 'application/octet-stream'
        )
        response['Content-Disposition'] = f'attachment; filename="{document.original_filename}_v{version_number}"'
        return response
    except Exception:
        return HttpResponse('Fehler beim Herunterladen', status=500)
