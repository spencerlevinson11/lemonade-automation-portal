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
        r.location_name = 'Distribution center'
        r.po_number = ''
        r.rpc_number = ''
        r.container_number = ''
        r.carrier = ''
        r.booking_number = ''
        r.bill_of_lading_number = ''
        r.notes = ''
        r.requested_date_text = ''
        r.eta_city = 'Destination port'
        r.assigned_to = 'Demo owner'
        r.origin_country = 'Netherlands'
        # Prevent rendering tags whose labels might contain client information.
        # Tag relations are suppressed in the shared dashboard template.
        changes = overrides.get(str(c.pk), {})
        if 'owner' in changes: r.assigned_to = changes['owner']
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

