"""Read-only live demonstration of Retriever's Order Tracker.

The demo shares no credentials and stores no OrderContainer copies. Transient
edits are kept in the current Django session, not in the production database.
"""
from datetime import date
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from .models import Company, OrderContainer, OrderContainerTrackingUpdate
from .services.tracker_customer_options import owner_names

DEMO_USERNAME = 'lemonadestandex'
SOURCE_USERNAME = 'retrieverpackaging'
SESSION_KEY = 'demo_order_tracker_overrides_v1'
DEMO_EDITABLE_FIELDS = ('customer_name','location_name','po_number','requested_date','requested_date_text','requested_asap','status','assigned_to','origin_country','rpc_number','loading_date','etd','eta','eta_city','estimated_delivery_date','booking_number','bill_of_lading_number','container_number','shipping_line_id','vessel_name','vessel_mmsi','vessel_imo','notes')
DATE_FIELDS = ('requested_date','loading_date','etd','eta','estimated_delivery_date')

def _field_value(field, value):
    if field in DATE_FIELDS:
        try: return date.fromisoformat(value) if value else None
        except (ValueError, TypeError): return None
    if field == 'requested_asap': return value == 'True'
    return value



def is_demo_user(user):
    return bool(getattr(user, 'is_authenticated', False) and
                user.username.casefold() == DEMO_USERNAME)


def _source_company():
    return Company.objects.filter(owner__username__iexact=SOURCE_USERNAME).first()


def _safe_name_map(containers):
    # Stable pseudonyms within each snapshot; customer names never enter HTML.
    names = sorted({c.customer_name.strip() for c in containers})
    return {name: f'Customer {index:02d}' for index, name in enumerate(names, 1)}


def _snapshot(request):
    source = _source_company()
    if source is None:
        return [], None
    containers = list(OrderContainer.objects.filter(company=source)
                      .order_by('-updated_at', '-created_at'))
    aliases = _safe_name_map(containers)
    changes = request.session.get(SESSION_KEY, {})
    identifiers = [c.pk for c in containers]
    latest = {}
    for update in (OrderContainerTrackingUpdate.objects.filter(container_id__in=identifiers)
                   .order_by('container_id', '-created_at', '-pk')):
        latest.setdefault(update.container_id, update)
    rows = []
    for c in containers:
        edit = changes.get(str(c.pk), {})
        api_update = latest.get(c.pk)
        # Show intentionally limited, safe order fields. Never expose customer,
        # location, reference numbers, notes, or raw JSONCargo responses.
        rows.append({
            'pk': c.pk,
            'alias': aliases.get(c.customer_name.strip(), 'Customer'),
            'order_label': f'Shipment {c.pk:05d}',
            'status': edit.get('status', c.status or 'Pending'),
            'owner': edit.get('owner', c.assigned_to or ''),
            'origin': edit.get('origin', 'Netherlands'),
            'etd': c.etd,
            'eta': edit.get('eta', c.eta.isoformat() if c.eta else ''),
            'api_eta': api_update.proposed_eta if api_update else None,
            'api_checked_at': api_update.created_at if api_update else None,
            'demo_modified': bool(edit),
            'archived': c.is_archived,
        })
    return rows, source


@login_required
def dashboard(request):
    if not is_demo_user(request.user):
        raise Http404
    rows, source = _snapshot(request)
    demo_company = Company.objects.filter(owner=request.user).first()
    owner_options = owner_names(demo_company) if demo_company else []
    return render(request, 'core/order_tracker_demo.html', {
        'rows': rows, 'source_available': source is not None,
        'owners': owner_options, 'count': len(rows),
    })


@login_required
@require_http_methods(['POST'])
def edit(request, pk):
    if not is_demo_user(request.user):
        raise Http404
    source = _source_company()
    if source is None:
        raise Http404
    get_object_or_404(OrderContainer, pk=pk, company=source)
    overrides = request.session.get(SESSION_KEY, {})
    status = (request.POST.get('status') or '')[:128]
    origin = (request.POST.get('origin') or '')[:100]
    owner = (request.POST.get('owner') or '')[:80]
    eta = (request.POST.get('eta') or '')
    if eta:
        try:
            date.fromisoformat(eta)
        except ValueError:
            messages.error(request, 'Enter a valid ETA date.')
            return redirect('order_tracker')
    overrides[str(pk)] = {'status': status, 'origin': origin, 'owner': owner, 'eta': eta}
    request.session[SESSION_KEY] = overrides
    request.session.modified = True
    messages.success(request, 'Demo changes saved only for this login session.')
    return redirect('order_tracker')


@login_required
@require_http_methods(['POST'])
def reset(request):
    if not is_demo_user(request.user):
        raise Http404
    request.session.pop(SESSION_KEY, None)
    request.session.modified = True
    return redirect('order_tracker')


def make_demo_containers(request, active, delivered):
    """Presentation copies only. Anonymize *before* template rendering."""
    from copy import copy
    from datetime import date
    originals = list(active) + list(delivered)
    names = sorted({(c.customer_name or '').strip() for c in originals})
    aliases = {name: f'Customer {i:02d}' for i, name in enumerate(names, 1)}
    overrides = request.session.get(SESSION_KEY, {})

    def clone(c):
        r = copy(c)
        r.customer_name = aliases.get((c.customer_name or '').strip(), 'Customer')
        # Do not expose proprietary client sites, shipment references, or IDs.
        r.location_name = c.location_name
        r.po_number = c.po_number
        r.rpc_number = c.rpc_number
        r.container_number = c.container_number
        r.carrier = c.carrier
        r.booking_number = c.booking_number
        r.bill_of_lading_number = c.bill_of_lading_number
        r.notes = ''
        r.requested_date_text = c.requested_date_text
        r.eta_city = c.eta_city
        r.assigned_to = c.assigned_to
        r.origin_country = c.origin_country or 'Netherlands'
        # Prevent rendering tags whose labels might contain client information.
        # Tag relations are suppressed in the shared dashboard template.
        changes = overrides.get(str(c.pk), {})
        if 'owner' in changes: r.assigned_to = changes['owner']
        for field, value in changes.get('fields', {}).items():
            if field in DEMO_EDITABLE_FIELDS:
                setattr(r, field, _field_value(field, value))
        if 'origin' in changes: r.origin_country = changes['origin']
        if 'status' in changes: r.status = changes['status']
        if 'eta' in changes:
            try: r.eta = date.fromisoformat(changes['eta']) if changes['eta'] else None
            except ValueError: pass
        if 'eta_city' in changes: r.eta_city = changes['eta_city']
        if 'estimated_delivery_date' in changes:
            try: r.estimated_delivery_date = date.fromisoformat(changes['estimated_delivery_date']) if changes['estimated_delivery_date'] else None
            except ValueError: pass
        if 'checked' in changes: r.tracker_checked = changes['checked']
        # API messages may include references or shipment identifiers; show only status.
        # Tracking annotations are attached later by the dashboard view, not model fields.
        # Never access a non-existent annotation here, and never expose raw API text.
        r.latest_jsoncargo_display_text = ''
        r.latest_tracking_update = None
        r.latest_pending_tracking_update = None
        return r
    clones = [clone(c) for c in originals]
    return ([r for r in clones if (r.status or '').casefold() != 'delivered'],
            [r for r in clones if (r.status or '').casefold() == 'delivered'])


class _EmptyDemoTags:
    def all(self):
        return []


@login_required
@require_http_methods(['POST'])
def demo_action(request):
    """Allow on-screen demo edits without database writes or API calls."""
    from django.http import JsonResponse
    if not is_demo_user(request.user):
        raise Http404
    source = _source_company()
    if source is None:
        raise Http404
    action = request.POST.get('action', '')
    overlays = request.session.get(SESSION_KEY, {})
    ids = request.POST.getlist('container_ids')
    if action in ('refresh', 'reset'):
        if action == 'reset': overlays = {}
        request.session[SESSION_KEY] = overlays
        request.session.modified = True
        return redirect('order_tracker')
    if action == 'bulk_eta':
        ids = ids[:500]
    else:
        ids = [request.POST.get('container_id', '')]
    for raw in ids:
        try: pk = int(raw)
        except (TypeError, ValueError): continue
        if not OrderContainer.objects.filter(pk=pk, company=source).exists():
            continue
        change = dict(overlays.get(str(pk), {}))
        if action == 'bulk_eta':
            for field in ('eta', 'eta_city', 'estimated_delivery_date'):
                key = f'{field}_{pk}'
                if key in request.POST:
                    value = request.POST[key][:100]
                    if field != 'eta_city' and value:
                        try: date.fromisoformat(value)
                        except ValueError: continue
                    change[field] = value
        elif action == 'checked':
            change['checked'] = request.POST.get('checked') == '1'
        elif action == 'delivered':
            current = OrderContainer.objects.get(pk=pk, company=source)
            change['status'] = 'Delivered' if change.get('status', current.status).casefold() != 'delivered' else 'In Transit'
        elif action == 'edit':
            for field in ('owner','origin','status','eta'):
                if field in request.POST:
                    change[field] = request.POST[field][:100]
        overlays[str(pk)] = change
    request.session[SESSION_KEY] = overlays
    request.session.modified = True
    if action == 'checked' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'checked': change.get('checked', False)})
    return redirect('order_tracker')



@login_required
@require_http_methods(['GET', 'POST'])
def demo_order_detail(request, pk):
    """Render the actual order editor with session-only values; never save models."""
    from copy import copy
    from django.forms import inlineformset_factory
    from .forms import OrderContainerForm, OrderContainerLineForm, OrderContainerTagForm, OrderContainerDocumentForm
    from .models import OrderContainerLine, OrderContainerTag, OrderContainerDocument
    if not is_demo_user(request.user):
        raise Http404
    source = _source_company()
    if source is None:
        raise Http404
    original = get_object_or_404(OrderContainer, pk=pk, company=source)
    originals = list(OrderContainer.objects.filter(company=source))
    alias = _safe_name_map(originals).get((original.customer_name or '').strip(), 'Customer')
    overlay = request.session.get(SESSION_KEY, {})
    change = dict(overlay.get(str(pk), {}))
    demo_company = Company.objects.filter(owner=request.user).first()
    # Model instance is only a shallow presentation copy. All writes are diverted
    # into the authenticated demo session.
    container = copy(original)
    container.customer_name = alias
    container.notes = '' # Freeform notes may mention real customers.
    for field, value in change.get('fields', {}).items():
        if field in DEMO_EDITABLE_FIELDS:
            setattr(container, field, _field_value(field, value))
    for field, attr in [('owner','assigned_to'), ('origin','origin_country'), ('eta_city','eta_city')]:
        if field in change: setattr(container, attr, change[field])
    if 'status' in change: container.status = change['status']
    if 'eta' in change: container.eta = _field_value('eta', change['eta'])
    if 'estimated_delivery_date' in change: container.estimated_delivery_date = _field_value('estimated_delivery_date', change['estimated_delivery_date'])

    LineFormSet = inlineformset_factory(OrderContainer, OrderContainerLine, form=OrderContainerLineForm, extra=3, can_delete=True)
    TagFormSet = inlineformset_factory(OrderContainer, OrderContainerTag, form=OrderContainerTagForm, extra=2, can_delete=True)
    DocFormSet = inlineformset_factory(OrderContainer, OrderContainerDocument, form=OrderContainerDocumentForm, extra=1, can_delete=True)

    if request.method == 'POST':
        # Never call ModelForm.save(), formset.save() or any tracking API.
        form = OrderContainerForm(request.POST, instance=container, company=demo_company)
        lines = LineFormSet(request.POST, instance=original, prefix='lines')
        # Tags and documents are disabled in demo to avoid identifying information.
        if form.is_valid() and lines.is_valid():
            stored = {}
            for key in DEMO_EDITABLE_FIELDS:
                if key not in form.cleaned_data: continue
                value = form.cleaned_data[key]
                stored[key] = value.isoformat() if isinstance(value, date) else str(value) if value is not None else ''
            stored['customer_name'] = alias # never store real or user-supplied customer name
            # New editor values take precedence over older dashboard-level overrides.
            for key in ('owner','origin','status','eta','eta_city','estimated_delivery_date'):
                change.pop(key, None)
            change['fields'] = stored
            # Store only the order line fields as harmless JSON-compatible values.
            change['lines'] = [
                {'item_description': f.cleaned_data.get('item_description',''),
                 'pallets': f.cleaned_data.get('pallets') or 0,
                 'units_per_pallet': f.cleaned_data.get('units_per_pallet') or 0}
                for f in lines.forms if f.cleaned_data and not f.cleaned_data.get('DELETE')
            ]
            overlay[str(pk)] = change
            request.session[SESSION_KEY] = overlay
            request.session.modified = True
            messages.success(request, 'Demo changes applied temporarily. Retriever Packaging was not modified.')
            return redirect('order_tracker_demo_detail', pk=pk)
        messages.error(request, 'Please correct the highlighted fields.')
    else:
        form = OrderContainerForm(instance=container, company=demo_company)
        lines = LineFormSet(instance=original, prefix='lines')
        if 'lines' in change:
            # Display session-modified lines via an unbound formset's initial values.
            initial_lines = change['lines']
            for index, line_form in enumerate(lines.forms):
                if index < len(initial_lines):
                    for field, value in initial_lines[index].items():
                        if field in line_form.fields:
                            line_form.initial[field] = value

    # Never expose raw tags, uploaded documents, or customer-specific API payloads.
    tags = TagFormSet(instance=original, prefix='tags', queryset=OrderContainerTag.objects.none())
    docs = DocFormSet(instance=original, prefix='docs', queryset=OrderContainerDocument.objects.none())
    return render(request, 'core/order_container_edit.html', {
        'automation_name': 'Order Tracker', 'company': demo_company or source,
        'container': container, 'form': form, 'formset': lines,
        'doc_formset': docs, 'tag_formset': tags, 'demo_mode': True,
        'tracker_is_retriever': False,
        'tracker_owner_options': owner_names(demo_company) if demo_company else [],
        'pending_tracking_update': None, 'jsoncargo_data': {},
        'jsoncargo_display_eta': '', 'jsoncargo_next_destination': '',
        'jsoncargo_display_message': '',
    })



@login_required
@require_http_methods(['POST'])
def demo_sync_container(request, pk):
    """One real JSONCargo tracking operation on Retriever's original container.

    The only shared writes are JSONCargo tracking updates made by the existing
    tracker service. Demo form/session overlays are never saved to the source.
    """
    from django.core.exceptions import PermissionDenied
    from .services.jsoncargo_accounts import api_key_for_user
    from .services.jsoncargo_order_tracker import sync_one_container
    if not is_demo_user(request.user):
        raise Http404
    source = _source_company()
    if source is None:
        raise Http404
    container = get_object_or_404(OrderContainer, pk=pk, company=source)
    if container.is_archived:
        messages.error(request, 'Archived containers cannot be tracked.')
        return redirect('order_tracker_demo_detail', pk=pk)
    try:
        key = api_key_for_user(source.owner)
    except PermissionDenied:
        messages.error(request, 'Source tracking is currently unavailable.')
        return redirect('order_tracker_demo_detail', pk=pk)
    try:
        outcome, _pending = sync_one_container(container, api_key=key)
        if outcome == 'skipped_in_progress':
            messages.info(request, 'Tracking is already running for this container; no second request was sent.')
        else:
            messages.success(request, 'Tracking completed using the shared source account.')
    except Exception:
        messages.error(request, 'Tracking could not be completed.')
    return redirect('order_tracker_demo_detail', pk=pk)


@login_required
@require_http_methods(['POST'])
def demo_sync_bulk(request):
    """Launch standard source-company JSONCargo sync under the source key.

    The job is recorded in the demo's session, not as a second customer/key.
    """
    import json
    import os
    import subprocess
    import sys
    import uuid
    from django.conf import settings
    from django.core.exceptions import PermissionDenied
    from .services.jsoncargo_accounts import api_key_for_user
    from .views import _jsoncargo_sync_status_path
    if not is_demo_user(request.user):
        raise Http404
    source = _source_company()
    if source is None:
        raise Http404
    try:
        api_key_for_user(source.owner)
    except PermissionDenied:
        messages.error(request, 'Source tracking is currently unavailable.')
        return redirect('order_tracker')
    scope = request.POST.get('sync_scope', 'all')
    if scope not in ('all', 'owner', 'customer_city'):
        raise Http404
    owner = request.POST.get('owner', '').strip()[:80]
    customer = request.POST.get('customer', '').strip()[:160]
    city = request.POST.get('city', '').strip()[:160]
    if scope == 'owner' and not owner:
        messages.error(request, 'Choose an owner first.')
        return redirect('order_tracker')
    if scope == 'customer_city' and not (customer or city):
        messages.error(request, 'Enter a customer placeholder or city first.')
        return redirect('order_tracker')
    if customer:
        all_names = list(OrderContainer.objects.filter(company=source).values_list('customer_name', flat=True))
        alias_map = _safe_name_map([type('Row', (), {'customer_name': n or ''})() for n in all_names])
        reverse = {alias.casefold(): real for real, alias in alias_map.items()}
        customer = reverse.get(customer.casefold(), '')
        if not customer:
            messages.error(request, 'Choose an available demo customer placeholder.')
            return redirect('order_tracker')
    job_id = uuid.uuid4().hex
    file = _jsoncargo_sync_status_path(job_id)
    file.parent.mkdir(parents=True, exist_ok=True)
    # Initialize progress before launching the subprocess. Otherwise the
    # redirect may reach the progress view before its first status write.
    file.write_text(json.dumps({
        'state': 'queued',
        'user_id': source.owner_id,
        'label': 'Demo requested sync',
        'message': 'JSONCargo sync is queued...',
        'total': 0, 'checked': 0, 'created': 0,
        'updated': 0, 'skipped': 0, 'errors': 0, 'current': '',
    }), encoding='utf-8')
    args = [sys.executable, 'manage.py', 'jsoncargo_sync_order_tracker',
            '--user-id', str(source.owner_id), '--company-id', str(source.pk),
            '--status-file', str(file), '--sync-scope', scope,
            '--label', 'Demo requested sync', '--limit', os.getenv('JSONCARGO_WEB_SYNC_LIMIT', '500')]
    if owner: args += ['--owner', owner]
    if customer: args += ['--customer', customer]
    if city: args += ['--city', city]
    try:
        with open(file.with_suffix('.log'), 'ab') as log_file:
            subprocess.Popen(args, cwd=str(settings.BASE_DIR), stdout=log_file,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             close_fds=True, start_new_session=True)
    except OSError:
        file.unlink(missing_ok=True)
        messages.error(request, 'Could not start tracking.')
        return redirect('order_tracker')
    jobs = request.session.get('demo_sync_jobs_v1', [])[-9:]
    jobs.append(job_id)
    request.session['demo_sync_jobs_v1'] = jobs
    return redirect('order_tracker_jsoncargo_sync_progress', job_id=job_id)

