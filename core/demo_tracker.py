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
DEMO_TRACKING_SNAPSHOT_KEY = 'demo_tracker_tracking_snapshot_v1'
DEMO_CREATED_KEY = 'demo_created_containers_v1'
DEMO_ID_START = 2000000000

DEMO_EDITABLE_FIELDS = ('customer_name','location_name','po_number','requested_date','requested_date_text','requested_asap','status','assigned_to','origin_country','rpc_number','loading_date','etd','eta','eta_city','estimated_delivery_date','booking_number','bill_of_lading_number','container_number','shipping_line_id','vessel_name','vessel_mmsi','vessel_imo','notes')
DATE_FIELDS = ('requested_date','loading_date','etd','eta','estimated_delivery_date')

class DemoTrackingDisplay:
    """Template-compatible view of a JSONCargo result; never a database object."""
    def __init__(self, values):
        self.kind = values.get('kind', '')
        self.status = values.get('status', '')
        self.proposed_eta = values.get('eta') or None
        self.proposed_eta_city = values.get('city', '')
        self.note = ''
        self.id = 0
        self.pk = 0
        self.source_last_updated = None

    def get_kind_display(self):
        return self.kind.replace('_', ' ').title()

    def get_status_display(self):
        return self.status.replace('_', ' ').title()


def preserve_demo_tracking_results(request, containers):
    """Keep sanitized results while users sort/filter during one login session.

    Source records remain authoritative when they contain a newer result.
    The snapshot contains no real customer names or raw provider payloads.
    """
    if not is_demo_user(request.user):
        return
    snapshots = dict(request.session.get(DEMO_TRACKING_SNAPSHOT_KEY, {}))
    changed = False
    for container in containers:
        key = str(container.pk)
        latest = getattr(container, 'latest_tracking_update', None)
        if latest is not None:
            values = {
                'kind': str(getattr(latest, 'kind', '') or ''),
                'status': str(getattr(latest, 'status', '') or ''),
                'eta': str(getattr(latest, 'proposed_eta', '') or ''),
                'city': str(getattr(latest, 'proposed_eta_city', '') or '')[:160],
                'record_id': int(getattr(latest, 'pk', 0) or 0),
            }
            old = snapshots.get(key, {})
            if not old.get('demo_only') and values['record_id'] >= int(old.get('record_id', 0)):
                if old != values:
                    snapshots[key] = values
                    changed = True
        saved = snapshots.get(key)
        if saved:
            # Never modify actual OrderContainerTrackingUpdate rows.
            # Expose the same last result on all subsequent dashboard views.
            display = DemoTrackingDisplay(saved)
            container.latest_tracking_update = display
            if saved.get('demo_only') or getattr(container, 'latest_pending_tracking_update', None) is None:
                container.latest_pending_tracking_update = display if display.status == 'pending' else None
            container.latest_jsoncargo_display_text = (
                ' '.join(v for v in (saved.get('eta', ''), saved.get('city', '')) if v)
                or ('No ETA returned' if display.kind != 'error' else '')
            )
    if changed:
        request.session[DEMO_TRACKING_SNAPSHOT_KEY] = snapshots
        request.session.modified = True


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
    names = sorted({(c.customer_name or '').strip() for c in containers})
    return {name: f'Customer {index:02d}' for index, name in enumerate(names, 1)}


def demo_customer_aliases(source):
    """Single customer-alias mapping for dashboard, search, and demo syncing.

    Exclude archived orders in all three locations. Otherwise archived clients
    silently shift the visible Customer 01 / Customer 02 assignments used by
    the Sync by Customer form.
    """
    if source is None:
        return {}
    names = (OrderContainer.objects.filter(company=source, is_archived=False)
             .values_list('customer_name', flat=True).distinct())
    return _safe_name_map([type('NameOnly', (), {'customer_name': name})() for name in names])


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
    request.session.pop(DEMO_CREATED_KEY, None)
    request.session.pop(DEMO_TRACKING_SNAPSHOT_KEY, None)
    request.session.modified = True
    return redirect('order_tracker')


def make_demo_containers(request, active, delivered):
    """Presentation copies only. Anonymize *before* template rendering."""
    from copy import copy
    from datetime import date
    originals = list(active) + list(delivered)
    # Use one stable set of aliases for the entire source company, including
    # orders excluded by dashboard filters, so Customer 12 never changes identity.
    source = _source_company()
    aliases = demo_customer_aliases(source)
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



def _session_created(request):
    return request.session.get(DEMO_CREATED_KEY, {})


def _demo_container(request, pk, source):
    """Return a detached source record or a session-only demo-created container."""
    from copy import copy
    created = _session_created(request).get(str(pk))
    if created is not None:
        obj = OrderContainer(pk=pk, company=source)
        for field in DEMO_EDITABLE_FIELDS + ('carrier',):
            if field in created:
                setattr(obj, field, _field_value(field, created[field]))
        return obj
    return copy(get_object_or_404(OrderContainer, pk=pk, company=source))


@login_required
@require_http_methods(['POST'])
def demo_create_container(request):
    """Quick Add: no OrderContainer is inserted into the database."""
    if not is_demo_user(request.user):
        raise Http404
    customer = (request.POST.get('customer_name') or '').strip()[:160]
    if not customer:
        messages.error(request, 'Enter a demo customer name.')
        return redirect('order_tracker')
    created = dict(_session_created(request))
    if len(created) >= 100:
        messages.error(request, 'This demo session has reached its 100-container limit.')
        return redirect('order_tracker')
    next_id = max([DEMO_ID_START - 1] + [int(x) for x in created]) + 1
    fields = {key: (request.POST.get(key) or '')[:200] for key in DEMO_EDITABLE_FIELDS + ('carrier',)}
    fields['customer_name'] = customer
    fields['status'] = fields.get('status') or 'Booked'
    created[str(next_id)] = fields
    request.session[DEMO_CREATED_KEY] = created
    request.session.modified = True
    messages.success(request, 'Demo container added temporarily. It will disappear at logout.')
    return redirect('order_tracker_demo_detail', pk=next_id)


def _demo_api_lookup(request, container, source):
    """One direct container lookup, with only sanitized display values saved in session.

    No production sync service is called, because that service writes to source
    OrderContainer and OrderContainerTrackingUpdate records.
    """
    from django.core.exceptions import PermissionDenied
    from .services.jsoncargo_accounts import api_key_for_user
    from .services.jsoncargo_order_tracker import (
        _attempt_container_lookup, _jsoncargo_data, _extract_eta_city,
        tracking_reference_for_jsoncargo,
    )
    if not (container.container_number or '').strip():
        return False, 'This container has no tracking number.'
    try:
        api_key = api_key_for_user(source.owner)
    except PermissionDenied:
        return False, 'Source tracking credentials are unavailable.'
    reference = tracking_reference_for_jsoncargo(container)
    carrier = container.jsoncargo_shipping_line_param()
    tracking, err, attempts = _attempt_container_lookup(
        tracking_reference=reference, api_key=api_key, shipping_line=carrier,
    )
    if err:
        result = {'kind': 'error', 'status': 'pending', 'eta': '', 'city': '',
                  'message': 'JSONCargo could not retrieve a tracking update.', 'record_id': 0}
    else:
        data = _jsoncargo_data(tracking)
        eta, city = _extract_eta_city(data)
        result = {'kind': 'change', 'status': 'pending', 'eta': str(eta) if eta else '',
                  'city': str(city or '')[:160], 'message': '', 'record_id': 0,
                  'container_status': str(data.get('container_status') or '')[:120]}
    snapshots = dict(request.session.get(DEMO_TRACKING_SNAPSHOT_KEY, {}))
    result['demo_only'] = True
    snapshots[str(container.pk)] = result
    request.session[DEMO_TRACKING_SNAPSHOT_KEY] = snapshots
    request.session.modified = True
    return True, result


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
    original = _demo_container(request, pk, source)
    originals = list(OrderContainer.objects.filter(company=source))
    alias = (original.customer_name if str(pk) in _session_created(request) else
             demo_customer_aliases(source).get((original.customer_name or '').strip(), 'Customer'))
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
        'pending_tracking_update': (DemoTrackingDisplay(request.session[DEMO_TRACKING_SNAPSHOT_KEY][str(pk)])
            if str(pk) in request.session.get(DEMO_TRACKING_SNAPSHOT_KEY, {}) else None),
        'jsoncargo_data': {'container_status': request.session.get(DEMO_TRACKING_SNAPSHOT_KEY, {}).get(str(pk), {}).get('container_status', '')},
        'jsoncargo_display_eta': request.session.get(DEMO_TRACKING_SNAPSHOT_KEY, {}).get(str(pk), {}).get('eta', ''),
        'jsoncargo_next_destination': request.session.get(DEMO_TRACKING_SNAPSHOT_KEY, {}).get(str(pk), {}).get('city', ''),
        'jsoncargo_display_message': request.session.get(DEMO_TRACKING_SNAPSHOT_KEY, {}).get(str(pk), {}).get('message', ''),
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
    container = _demo_container(request, pk, source)
    if container.is_archived:
        messages.error(request, 'Archived containers cannot be tracked.')
        return redirect('order_tracker_demo_detail', pk=pk)
    try:
        succeeded, result = _demo_api_lookup(request, container, source)
        if succeeded:
            messages.success(request, 'JSONCargo result saved to this demo session only.')
        else:
            messages.error(request, result)
    except Exception:
        messages.error(request, 'JSONCargo tracking could not be completed.')
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
        alias_map = demo_customer_aliases(source)
        reverse = {alias.casefold(): real for real, alias in alias_map.items()}
        customer = reverse.get(customer.casefold(), '')
        if not customer:
            messages.error(request, 'Choose an available demo customer placeholder.')
            return redirect('order_tracker')
    # Never launch the production management command from a demo request.
    # It writes tracking results into the source company's records.
    eligible = OrderContainer.objects.filter(company=source, is_archived=False).exclude(status__iexact='Delivered')
    if owner:
        eligible = eligible.filter(assigned_to__iexact=owner)
    if customer:
        eligible = eligible.filter(customer_name__iexact=customer)
    if city:
        eligible = eligible.filter(location_name__icontains=city)
    eligible = eligible.exclude(container_number='')[:50]
    count = 0
    for c in eligible:
        try:
            success, _ = _demo_api_lookup(request, c, source)
            count += bool(success)
        except Exception:
            pass
    messages.info(request, f'Demo tracking results saved for {count} container(s) in this session.')
    return redirect('order_tracker')




class _DemoRecapLineCollection:
    """Supply line objects to the existing recap renderer without DB writes."""
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self

    def __iter__(self):
        return iter(self._rows)

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, index):
        return self._rows[index]


def demo_recap_containers(request):
    """Detached, anonymized orders including session edits and Quick Add/PDF orders."""
    from copy import copy
    from types import SimpleNamespace

    if not is_demo_user(request.user):
        raise Http404
    source = _source_company()
    if source is None:
        return []

    aliases = demo_customer_aliases(source)
    overrides = request.session.get(SESSION_KEY, {})
    rows = []
    originals = (OrderContainer.objects.filter(company=source, is_archived=False)
                 .prefetch_related('lines'))

    def attach_lines(clone, original_lines, change):
        if 'lines' in change:
            raw = change['lines']
            line_rows = [SimpleNamespace(
                item_description=str(line.get('item_description') or ''),
                pallets=int(line.get('pallets') or 0),
                units_per_pallet=int(line.get('units_per_pallet') or 0),
                total_units=int(line.get('total_units') or
                                (int(line.get('pallets') or 0) * int(line.get('units_per_pallet') or 0)))
            ) for line in raw]
        else:
            line_rows = [copy(line) for line in original_lines]
        # A prefetched line relation may use Django's relation descriptor;
        # assign a per-instance cached collection instead of touching the DB.
        clone._prefetched_objects_cache = {'lines': _DemoRecapLineCollection(line_rows)}

    for original in originals:
        row = copy(original)
        row.customer_name = aliases.get((original.customer_name or '').strip(), 'Customer')
        row.notes = ''
        change = overrides.get(str(original.pk), {})
        for field, value in change.get('fields', {}).items():
            if field in DEMO_EDITABLE_FIELDS and field != 'customer_name':
                setattr(row, field, _field_value(field, value))
        for key, attr in (('owner', 'assigned_to'), ('origin', 'origin_country'),
                          ('status', 'status'), ('eta', 'eta'),
                          ('eta_city', 'eta_city'),
                          ('estimated_delivery_date', 'estimated_delivery_date')):
            if key in change:
                setattr(row, attr, _field_value(attr, change[key]))
        attach_lines(row, list(original.lines.all()), change)
        rows.append(row)

    for pk, data in _session_created(request).items():
        row = OrderContainer(pk=int(pk), company=source)
        for field in DEMO_EDITABLE_FIELDS:
            if field in data:
                setattr(row, field, _field_value(field, data[field]))
        change = overrides.get(str(pk), {})
        for field, value in change.get('fields', {}).items():
            if field in DEMO_EDITABLE_FIELDS:
                setattr(row, field, _field_value(field, value))
        for key, attr in (('owner', 'assigned_to'), ('origin', 'origin_country'),
                          ('status', 'status'), ('eta', 'eta'),
                          ('estimated_delivery_date', 'estimated_delivery_date')):
            if key in change:
                setattr(row, attr, _field_value(attr, change[key]))
        attach_lines(row, [], change)
        rows.append(row)
    return rows


