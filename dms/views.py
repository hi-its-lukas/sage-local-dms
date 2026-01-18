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
    FileCategory, DocumentVersion, AuditLog, SystemSettings, SystemLog
)
from .encryption import encrypt_data, decrypt_data, calculate_sha256
import magic


@login_required
@permission_required('dms.change_systemsettings', raise_exception=True)
def sage_sync_dashboard(request):
    """Dashboard for Sage Cloud synchronization"""
    settings = SystemSettings.load()
    recent_logs = SystemLog.objects.filter(
        source__icontains='Sage'
    ).order_by('-timestamp')[:20]
    
    is_configured = bool(settings.sage_cloud_api_url and settings.encrypted_sage_cloud_api_key)
    
    return render(request, 'dms/sage_sync.html', {
        'settings': settings,
        'recent_logs': recent_logs,
        'is_configured': is_configured,
    })


@login_required
@permission_required('dms.change_systemsettings', raise_exception=True)
@require_http_methods(['POST'])
def sage_sync_employees(request):
    """Trigger Sage Cloud employee sync"""
    from .connectors.sage_cloud import SageCloudConnector
    
    try:
        connector = SageCloudConnector()
        if connector.connect():
            stats = connector.sync_employees()
            messages.success(request, 
                f"Mitarbeiter-Sync erfolgreich: {stats['created']} erstellt, "
                f"{stats['updated']} aktualisiert, {stats['files_created']} Akten erstellt")
        else:
            messages.error(request, "Verbindung zu Sage HR Cloud fehlgeschlagen. Prüfen Sie die Einstellungen.")
    except Exception as e:
        messages.error(request, f"Fehler beim Sync: {str(e)}")
    
    return redirect('dms:sage_sync_dashboard')


@login_required
@permission_required('dms.change_systemsettings', raise_exception=True)
@require_http_methods(['POST'])
def sage_sync_leave_requests(request):
    """Trigger Sage Cloud leave requests import"""
    from .connectors.sage_cloud import SageCloudConnector
    from datetime import timedelta
    from django.utils import timezone
    
    try:
        connector = SageCloudConnector()
        since_date = (timezone.now() - timedelta(days=30)).date()
        stats = connector.import_leave_requests(since_date)
        messages.success(request, 
            f"Urlaubsanträge-Import erfolgreich: {stats['imported']} importiert, "
            f"{stats['skipped']} übersprungen")
    except Exception as e:
        messages.error(request, f"Fehler beim Import: {str(e)}")
    
    return redirect('dms:sage_sync_dashboard')


@login_required
@permission_required('dms.change_systemsettings', raise_exception=True)
@require_http_methods(['POST'])
def sage_sync_timesheets(request):
    """Trigger Sage Cloud timesheets import"""
    from .connectors.sage_cloud import SageCloudConnector
    from django.utils import timezone
    
    try:
        now = timezone.now()
        if now.month == 1:
            year, month = now.year - 1, 12
        else:
            year, month = now.year, now.month - 1
        
        connector = SageCloudConnector()
        stats = connector.import_timesheets(year, month)
        messages.success(request, 
            f"Zeiterfassungs-Import für {month:02d}/{year} erfolgreich: "
            f"{stats['imported']} importiert, {stats['skipped']} übersprungen")
    except Exception as e:
        messages.error(request, f"Fehler beim Import: {str(e)}")
    
    return redirect('dms:sage_sync_dashboard')


@login_required
def index(request):
    from .models import ScanJob
    
    recent_documents = Document.objects.select_related('employee', 'document_type').order_by('-updated_at')[:10]
    open_tasks = Task.objects.filter(status='OPEN')[:5]
    
    active_scans = ScanJob.objects.filter(status='RUNNING')
    recent_scans = ScanJob.objects.exclude(status='RUNNING')[:3]
    
    stats = {
        'total_documents': Document.objects.count(),
        'unassigned': Document.objects.filter(status='UNASSIGNED').count(),
        'review_needed': Document.objects.filter(status='REVIEW_NEEDED').count(),
        'open_tasks': Task.objects.filter(status='OPEN').count(),
        'total_personnel_files': PersonnelFile.objects.count(),
    }
    
    return render(request, 'dms/index.html', {
        'recent_documents': recent_documents,
        'open_tasks': open_tasks,
        'stats': stats,
        'active_scans': active_scans,
        'recent_scans': recent_scans,
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
    document_type = request.GET.get('document_type')
    employee = request.GET.get('employee')
    tenant_id = request.GET.get('tenant')
    file_type = request.GET.get('file_type')
    filename = request.GET.get('filename')
    period_year = request.GET.get('period_year')
    period_month = request.GET.get('period_month')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    if status:
        documents = documents.filter(status=status)
    if source:
        documents = documents.filter(source=source)
    if document_type:
        documents = documents.filter(document_type_id=document_type)
    if employee:
        documents = documents.filter(
            Q(employee__first_name__icontains=employee) |
            Q(employee__last_name__icontains=employee)
        )
    if search:
        documents = documents.filter(
            Q(title__icontains=search) | 
            Q(original_filename__icontains=search)
        )
    if tenant_id:
        documents = documents.filter(tenant_id=tenant_id)
    if file_type:
        documents = documents.filter(file_extension=file_type)
    if filename:
        documents = documents.filter(original_filename__icontains=filename)
    if period_year:
        documents = documents.filter(period_year=int(period_year))
    if period_month:
        documents = documents.filter(period_month=int(period_month))
    if date_from:
        from datetime import datetime
        documents = documents.filter(created_at__gte=datetime.strptime(date_from, '%Y-%m-%d'))
    if date_to:
        from datetime import datetime, timedelta
        date_to_dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
        documents = documents.filter(created_at__lt=date_to_dt)
    
    documents = documents.select_related('employee', 'document_type', 'owner', 'tenant').order_by('-created_at')
    
    paginator = Paginator(documents, 25)
    page = request.GET.get('page', 1)
    documents = paginator.get_page(page)
    
    from .models import DocumentType, Tenant
    document_types = DocumentType.objects.filter(is_active=True)
    tenants = Tenant.objects.all().order_by('name')
    
    current_year = timezone.now().year
    period_years = list(range(current_year, current_year - 5, -1))
    
    return render(request, 'dms/document_list.html', {
        'documents': documents,
        'status_choices': Document.STATUS_CHOICES,
        'source_choices': Document.SOURCE_CHOICES,
        'document_types': document_types,
        'tenants': tenants,
        'period_years': period_years,
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
def document_view(request, pk):
    document = get_object_or_404(Document, pk=pk)
    
    if not _can_access_document(request.user, document):
        return HttpResponse('Permission denied', status=403)
    
    try:
        decrypted_content = decrypt_data(document.encrypted_content)
        
        _log_audit(request, 'VIEW', document=document)
        
        response = HttpResponse(
            decrypted_content,
            content_type=document.mime_type or 'application/octet-stream'
        )
        response['Content-Disposition'] = f'inline; filename="{document.original_filename}"'
        return response
    except Exception as e:
        return HttpResponse('Error viewing file', status=500)


@login_required
def document_page_thumbnail(request, pk, page_num):
    """Generiert ein Thumbnail-Bild für eine PDF-Seite."""
    import fitz
    
    document = get_object_or_404(Document, pk=pk)
    
    if not _can_access_document(request.user, document):
        return HttpResponse('Permission denied', status=403)
    
    if document.mime_type != 'application/pdf':
        return HttpResponse('Not a PDF', status=400)
    
    try:
        decrypted_content = decrypt_data(document.encrypted_content)
        pdf_doc = fitz.open(stream=decrypted_content, filetype='pdf')
        
        page_idx = page_num - 1
        if page_idx < 0 or page_idx >= len(pdf_doc):
            pdf_doc.close()
            return HttpResponse('Page not found', status=404)
        
        page = pdf_doc[page_idx]
        # Höhere Auflösung für bessere Lesbarkeit
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        img_data = pix.tobytes("png")
        
        pdf_doc.close()
        
        response = HttpResponse(img_data, content_type='image/png')
        response['Cache-Control'] = 'public, max-age=3600'
        return response
        
    except Exception as e:
        return HttpResponse(f'Error: {str(e)}', status=500)


@login_required
def document_edit(request, pk):
    from .forms import DocumentEditForm
    
    document = get_object_or_404(Document, pk=pk)
    
    if not _can_access_document(request.user, document):
        return HttpResponse('Permission denied', status=403)
    
    if request.method == 'POST':
        form = DocumentEditForm(request.POST, instance=document, tenant=document.tenant)
        if form.is_valid():
            old_status = document.status
            old_employee = document.employee
            
            document = form.save()
            
            changes = []
            if old_status != document.status:
                changes.append(f'Status: {old_status} → {document.status}')
            if old_employee != document.employee:
                old_name = old_employee.full_name if old_employee else 'Nicht zugewiesen'
                new_name = document.employee.full_name if document.employee else 'Nicht zugewiesen'
                changes.append(f'Mitarbeiter: {old_name} → {new_name}')
            
            _log_audit(request, 'EDIT', document=document, details={
                'changes': changes
            })
            
            messages.success(request, 'Dokument wurde erfolgreich aktualisiert.')
            return redirect('dms:document_detail', pk=document.pk)
    else:
        form = DocumentEditForm(instance=document, tenant=document.tenant)
    
    return render(request, 'dms/document_edit.html', {
        'document': document,
        'form': form
    })


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


@login_required
@require_http_methods(['POST'])
def bulk_edit_documents(request):
    """
    Paperless-ngx Style Bulk-Bearbeitung von Dokumenten.
    Ermöglicht Massenänderungen von Status, Mitarbeiter, Dokumenttyp und Tags.
    """
    from .forms import BulkEditForm
    from .models import Tag, DocumentTag
    import json
    
    form = BulkEditForm(request.POST)
    
    if not form.is_valid():
        return JsonResponse({
            'success': False, 
            'error': 'Ungültige Formulardaten',
            'errors': form.errors
        }, status=400)
    
    try:
        document_ids = json.loads(form.cleaned_data['document_ids'])
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Ungültige Dokument-IDs'}, status=400)
    
    if not document_ids:
        return JsonResponse({'success': False, 'error': 'Keine Dokumente ausgewählt'}, status=400)
    
    documents = Document.objects.filter(id__in=document_ids)
    action = form.cleaned_data['action']
    updated_count = 0
    
    try:
        if action == 'set_status' and form.cleaned_data['status']:
            updated_count = documents.update(status=form.cleaned_data['status'])
            
        elif action == 'set_employee':
            employee = form.cleaned_data['employee']
            updated_count = documents.update(
                employee=employee,
                status='ASSIGNED' if employee else 'UNASSIGNED'
            )
            
        elif action == 'set_document_type':
            updated_count = documents.update(document_type=form.cleaned_data['document_type'])
            
        elif action == 'add_tags':
            tags = form.cleaned_data['tags']
            for doc in documents:
                for tag in tags:
                    DocumentTag.objects.get_or_create(
                        document=doc,
                        tag=tag,
                        defaults={'added_by': request.user}
                    )
                updated_count += 1
                
        elif action == 'remove_tags':
            tags = form.cleaned_data['tags']
            for doc in documents:
                DocumentTag.objects.filter(document=doc, tag__in=tags).delete()
                updated_count += 1
                
        elif action == 'delete':
            if not request.user.has_perm('dms.delete_document'):
                return JsonResponse({
                    'success': False, 
                    'error': 'Keine Berechtigung zum Löschen'
                }, status=403)
            updated_count = documents.count()
            documents.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'{updated_count} Dokument(e) aktualisiert',
            'updated_count': updated_count
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'Fehler bei der Verarbeitung: {str(e)}'
        }, status=500)


@login_required
def fulltext_search(request):
    """
    Paperless-ngx Style Volltext-Suche mit PostgreSQL Full-Text Search.
    Unterstützt Highlighting und Ranking.
    """
    from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank, SearchHeadline
    from django.db.models import F
    
    query = request.GET.get('q', '').strip()
    
    if not query:
        return render(request, 'dms/fulltext_search.html', {
            'query': '',
            'results': [],
            'total_count': 0,
        })
    
    # PostgreSQL Full-Text Search
    search_vector = SearchVector('title', weight='A') + \
                    SearchVector('original_filename', weight='B') + \
                    SearchVector('notes', weight='C')
    
    search_query = SearchQuery(query, config='german')
    
    results = Document.objects.annotate(
        search=search_vector,
        rank=SearchRank(search_vector, search_query),
        headline=SearchHeadline(
            'title',
            search_query,
            config='german',
            start_sel='<mark>',
            stop_sel='</mark>',
            max_words=50,
            min_words=20
        )
    ).filter(
        search=search_query
    ).order_by('-rank').select_related('employee', 'document_type')[:100]
    
    # Auto-Complete Vorschläge aus häufigen Dokumenttiteln
    suggestions = []
    if len(query) >= 2:
        suggestions = Document.objects.filter(
            title__icontains=query
        ).values_list('title', flat=True).distinct()[:5]
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # AJAX-Response für Auto-Complete
        return JsonResponse({
            'suggestions': list(suggestions),
            'results': [
                {
                    'id': str(doc.id),
                    'title': doc.title,
                    'headline': doc.headline if hasattr(doc, 'headline') else doc.title,
                    'employee': doc.employee.full_name if doc.employee else None,
                    'document_type': doc.document_type.name if doc.document_type else None,
                    'created_at': doc.created_at.isoformat(),
                    'rank': float(doc.rank) if hasattr(doc, 'rank') else 0,
                }
                for doc in results[:20]
            ],
            'total_count': results.count(),
        })
    
    return render(request, 'dms/fulltext_search.html', {
        'query': query,
        'results': results,
        'total_count': results.count(),
        'suggestions': suggestions,
    })


@login_required
def system_logs(request):
    """Live-Ansicht der Systemlogs"""
    source_filter = request.GET.get('source', '')
    level_filter = request.GET.get('level', '')
    limit = int(request.GET.get('limit', 100))
    
    logs = SystemLog.objects.all().order_by('-timestamp')
    
    if source_filter:
        logs = logs.filter(source__icontains=source_filter)
    if level_filter:
        logs = logs.filter(level=level_filter)
    
    logs = logs[:limit]
    
    # Verfügbare Filter-Optionen
    sources = SystemLog.objects.values_list('source', flat=True).distinct()
    levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'logs': [
                {
                    'id': log.id,
                    'timestamp': log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'level': log.level,
                    'source': log.source,
                    'message': log.message,
                    'details': log.details,
                }
                for log in logs
            ]
        })
    
    return render(request, 'dms/system_logs.html', {
        'logs': logs,
        'sources': sources,
        'levels': levels,
        'current_source': source_filter,
        'current_level': level_filter,
        'current_limit': limit,
    })


@login_required
def document_split(request, pk):
    """Manuelles Teilen eines PDF-Dokuments nach Seitenbereichen"""
    import tempfile
    from pathlib import Path
    import fitz
    
    document = get_object_or_404(Document, pk=pk)
    
    if not _can_access_document(request.user, document):
        return HttpResponse('Permission denied', status=403)
    
    if document.mime_type != 'application/pdf':
        messages.error(request, 'Nur PDF-Dokumente können geteilt werden.')
        return redirect('dms:document_detail', pk=pk)
    
    try:
        decrypted_content = decrypt_data(document.encrypted_content)
        pdf_doc = fitz.open(stream=decrypted_content, filetype='pdf')
        page_count = len(pdf_doc)
        pdf_doc.close()
    except Exception as e:
        messages.error(request, f'Fehler beim Lesen des PDFs: {str(e)}')
        return redirect('dms:document_detail', pk=pk)
    
    from .models import Tenant
    # Zeige alle aktiven Mitarbeiter, bevorzugt vom gleichen Mandanten
    employees = Employee.objects.filter(is_active=True).order_by('last_name', 'first_name')
    
    # Falls keine aktiven gefunden, zeige auch inaktive
    if not employees.exists():
        employees = Employee.objects.all().order_by('last_name', 'first_name')
    
    if request.method == 'POST':
        try:
            splits_data = json.loads(request.POST.get('splits', '[]'))
            
            if not splits_data:
                messages.error(request, 'Keine Split-Bereiche angegeben.')
                return redirect('dms:document_split', pk=pk)
            
            from .encryption import encrypt_data as enc_data, calculate_sha256_chunked
            from .tasks import auto_classify_document, log_system_event, parse_month_folder
            
            decrypted_content = decrypt_data(document.encrypted_content)
            pdf_doc = fitz.open(stream=decrypted_content, filetype='pdf')
            
            created_docs = []
            
            for split in splits_data:
                start_page = int(split.get('start', 1)) - 1
                end_page = int(split.get('end', 1))
                employee_id = split.get('employee_id')
                
                if start_page < 0 or end_page > page_count or start_page >= end_page:
                    continue
                
                new_pdf = fitz.open()
                new_pdf.insert_pdf(pdf_doc, from_page=start_page, to_page=end_page - 1)
                
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                    new_pdf.save(tmp.name)
                    new_pdf.close()
                    
                    with open(tmp.name, 'rb') as f:
                        split_content = f.read()
                    
                    split_encrypted = enc_data(split_content)
                    split_hash = calculate_sha256_chunked(tmp.name)
                    
                    Path(tmp.name).unlink()
                
                split_employee = None
                if employee_id:
                    split_employee = Employee.objects.filter(id=employee_id).first()
                
                metadata = document.metadata.copy() if document.metadata else {}
                metadata['split_from'] = document.original_filename
                metadata['split_pages'] = f"{start_page + 1}-{end_page}"
                metadata['manual_split'] = True
                metadata['split_from_document_id'] = str(document.id)
                
                month_folder = metadata.get('month_folder')
                
                emp_suffix = f"_MA{split_employee.employee_id}" if split_employee else f"_S{start_page + 1}-{end_page}"
                split_filename = f"{document.title}{emp_suffix}.pdf"
                
                period_year, period_month = parse_month_folder(month_folder)
                split_doc = Document.objects.create(
                    tenant=document.tenant,
                    title=f"{document.title} (S.{start_page + 1}-{end_page})",
                    original_filename=split_filename,
                    file_extension='.pdf',
                    mime_type='application/pdf',
                    encrypted_content=split_encrypted,
                    file_size=len(split_content),
                    employee=split_employee,
                    status='ASSIGNED' if split_employee else 'REVIEW_NEEDED',
                    source=document.source,
                    sha256_hash=split_hash,
                    metadata=metadata,
                    period_year=period_year,
                    period_month=period_month
                )
                
                auto_classify_document(split_doc, tenant=document.tenant)
                created_docs.append(split_doc)
            
            pdf_doc.close()
            
            if created_docs:
                log_system_event('INFO', 'ManualSplit', 
                    f"Dokument manuell geteilt: {document.original_filename} → {len(created_docs)} Teile",
                    {'original_id': str(document.id), 'split_count': len(created_docs)})
                
                document.delete()
                
                messages.success(request, f'{len(created_docs)} Dokumente erfolgreich erstellt. Original wurde entfernt.')
                return redirect('dms:document_list')
            else:
                messages.error(request, 'Keine gültigen Split-Bereiche.')
                
        except Exception as e:
            messages.error(request, f'Fehler beim Teilen: {str(e)}')
    
    return render(request, 'dms/document_split.html', {
        'document': document,
        'page_count': page_count,
        'page_range': range(1, page_count + 1),
        'employees': employees,
    })


@login_required
@permission_required('dms.change_systemsettings', raise_exception=True)
def admin_maintenance(request):
    """Admin maintenance dashboard for running management commands"""
    from .models import (
        Document, Employee, PersonnelFile, PersonnelFileEntry,
        FileCategory, DocumentType, Tenant, ScanJob
    )
    from django.utils import timezone
    from datetime import timedelta
    
    documents_with_type_and_employee = Document.objects.filter(
        document_type__isnull=False,
        employee__isnull=False,
        document_type__file_category__isnull=False
    )
    filed_doc_ids = PersonnelFileEntry.objects.values_list('document_id', flat=True)
    documents_pending = documents_with_type_and_employee.exclude(id__in=filed_doc_ids).count()
    
    orphaned_entries = PersonnelFileEntry.objects.filter(document__isnull=True).count()
    
    stale_cutoff = timezone.now() - timedelta(hours=2)
    stale_scanjobs = ScanJob.objects.filter(
        status='RUNNING',
        started_at__lt=stale_cutoff
    ).count()
    
    last_scan_job = ScanJob.objects.filter(status='COMPLETED').order_by('-finished_at').first()
    last_scan = last_scan_job.finished_at.strftime('%d.%m.%Y %H:%M') if last_scan_job else None
    
    stats = {
        'total_documents': Document.objects.count(),
        'total_employees': Employee.objects.filter(is_active=True).count(),
        'total_personnel_files': PersonnelFile.objects.count(),
        'documents_filed': PersonnelFileEntry.objects.count(),
        'documents_pending': documents_pending,
        'total_tenants': Tenant.objects.count(),
        'file_categories': FileCategory.objects.count(),
        'document_types': DocumentType.objects.count(),
        'linked_types': DocumentType.objects.filter(file_category__isnull=False).count(),
        'orphaned_entries': orphaned_entries,
        'stale_scanjobs': stale_scanjobs,
        'last_scan': last_scan,
    }
    
    recent_scanjobs = ScanJob.objects.order_by('-started_at')[:10]
    
    return render(request, 'dms/admin_maintenance.html', {
        'stats': stats,
        'recent_scanjobs': recent_scanjobs,
    })


@login_required
@permission_required('dms.change_systemsettings', raise_exception=True)
@require_http_methods(['POST'])
def admin_run_create_filing_plan(request):
    """Run create_filing_plan management command"""
    from django.core.management import call_command
    from io import StringIO
    
    try:
        out = StringIO()
        call_command('create_filing_plan', stdout=out)
        messages.success(request, 'Aktenplan erfolgreich erstellt/aktualisiert.')
    except Exception as e:
        messages.error(request, f'Fehler: {str(e)}')
    
    return redirect('dms:admin_maintenance')


@login_required
@permission_required('dms.change_systemsettings', raise_exception=True)
@require_http_methods(['POST'])
def admin_run_link_doctypes(request):
    """Run link_doctypes_categories management command"""
    from django.core.management import call_command
    from io import StringIO
    
    try:
        out = StringIO()
        call_command('link_doctypes_categories', stdout=out)
        messages.success(request, 'DocumentTypes erfolgreich mit FileCategories verknüpft.')
    except Exception as e:
        messages.error(request, f'Fehler: {str(e)}')
    
    return redirect('dms:admin_maintenance')


@login_required
@permission_required('dms.change_systemsettings', raise_exception=True)
@require_http_methods(['POST'])
def admin_run_fix_categories(request):
    """Run fix_doctype_categories management command"""
    from django.core.management import call_command
    from io import StringIO
    
    try:
        out = StringIO()
        call_command('fix_doctype_categories', stdout=out)
        output = out.getvalue()
        if 'aktualisiert' in output or 'korrigiert' in output:
            messages.success(request, 'Dokumenttyp-Kategorien erfolgreich korrigiert.')
        else:
            messages.info(request, 'Keine Korrekturen erforderlich.')
    except Exception as e:
        if 'DRY RUN' not in str(e):
            messages.error(request, f'Fehler: {str(e)}')
    
    return redirect('dms:admin_maintenance')


@login_required
@permission_required('dms.change_systemsettings', raise_exception=True)
@require_http_methods(['POST'])
def admin_run_file_documents(request):
    """File existing documents to personnel files"""
    from .models import Document, PersonnelFileEntry
    
    count = 0
    try:
        for doc in Document.objects.filter(
            document_type__isnull=False,
            employee__isnull=False,
            document_type__file_category__isnull=False
        ).select_related('document_type', 'document_type__file_category', 'employee'):
            pf = getattr(doc.employee, 'personnel_file', None)
            if not pf:
                continue
            
            exists = PersonnelFileEntry.objects.filter(
                personnel_file=pf,
                document=doc
            ).exists()
            
            if not exists:
                PersonnelFileEntry.objects.create(
                    personnel_file=pf,
                    document=doc,
                    category=doc.document_type.file_category,
                    notes=f'Automatisch abgelegt aus {doc.document_type.name}'
                )
                count += 1
        
        messages.success(request, f'{count} Dokumente in Personalakten abgelegt.')
    except Exception as e:
        messages.error(request, f'Fehler: {str(e)}')
    
    return redirect('dms:admin_maintenance')


@login_required
@permission_required('dms.change_systemsettings', raise_exception=True)
@require_http_methods(['POST'])
def admin_run_scan_sage(request):
    """Trigger Sage archive scan"""
    from .tasks import scan_sage_archive
    
    try:
        result = scan_sage_archive()
        if result:
            messages.success(request, f'Sage-Archiv gescannt: {result.get("files_processed", 0)} Dateien verarbeitet.')
        else:
            messages.warning(request, 'Scan läuft bereits oder konnte nicht gestartet werden.')
    except Exception as e:
        messages.error(request, f'Fehler: {str(e)}')
    
    return redirect('dms:admin_maintenance')


@login_required
@permission_required('dms.change_systemsettings', raise_exception=True)
@require_http_methods(['POST'])
def admin_run_cleanup_orphans(request):
    """Clean up orphaned personnel file entries"""
    from .models import PersonnelFileEntry
    
    try:
        orphaned = PersonnelFileEntry.objects.filter(document__isnull=True)
        count = orphaned.count()
        orphaned.delete()
        messages.success(request, f'{count} verwaiste Einträge gelöscht.')
    except Exception as e:
        messages.error(request, f'Fehler: {str(e)}')
    
    return redirect('dms:admin_maintenance')


@login_required
@permission_required('dms.change_systemsettings', raise_exception=True)
@require_http_methods(['POST'])
def admin_run_reset_locks(request):
    """Reset stale scan locks and failed scan jobs"""
    from .models import ScanJob
    from django.utils import timezone
    from datetime import timedelta
    import redis
    import os
    
    try:
        stale_cutoff = timezone.now() - timedelta(hours=2)
        stale_jobs = ScanJob.objects.filter(
            status='RUNNING',
            started_at__lt=stale_cutoff
        )
        job_count = stale_jobs.count()
        stale_jobs.update(status='FAILED', error_message='Manuell zurückgesetzt')
        
        lock_count = 0
        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        try:
            r = redis.from_url(redis_url)
            for key in r.scan_iter('dms:lock:*'):
                r.delete(key)
                lock_count += 1
        except Exception:
            pass
        
        messages.success(request, f'{job_count} fehlgeschlagene Jobs und {lock_count} Sperren zurückgesetzt.')
    except Exception as e:
        messages.error(request, f'Fehler: {str(e)}')
    
    return redirect('dms:admin_maintenance')
