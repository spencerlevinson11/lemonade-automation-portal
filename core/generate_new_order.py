"""Generic order PDF generator, company-scoped with session-only demo orders."""
from datetime import date
from io import BytesIO
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from xml.sax.saxutils import escape
from .models import Automation, Company, OrderContainer, OrderContainerLine
from .demo_tracker import is_demo_user, DEMO_CREATED_KEY, DEMO_ID_START

FIELDS = ('customer_name', 'location_name', 'po_number', 'rpc_number', 'container_number',
          'booking_number', 'bill_of_lading_number', 'assigned_to', 'origin_country',
          'status', 'requested_date', 'loading_date', 'etd', 'eta', 'estimated_delivery_date', 'notes')
DATE_FIELDS = ('requested_date', 'loading_date', 'etd', 'eta', 'estimated_delivery_date')


def _authorized_company(request):
    if request.user.is_superuser:
        raise Http404('Generate New Order requires a customer account.')
    company = Company.objects.filter(owner=request.user).first()
    if company is None:
        raise Http404('Account has no company.')
    names = list(Automation.objects.filter(company=company, is_active=True).values_list('name', flat=True))
    norm = {(name or '').strip().casefold() for name in names}
    if 'generate new order' not in norm or not any(name in norm for name in ('order tracker', 'order tracking')):
        raise Http404('Both Generate New Order and Order Tracker must be enabled for this account.')
    return company


def _extract(post):
    values = {key: (post.get(key) or '').strip() for key in FIELDS}
    errors = []
    for name in ('customer_name',):
        if not values[name]: errors.append('Customer is required.')
    for key in FIELDS:
        if len(values[key]) > (2000 if key == 'notes' else 255): errors.append(f'{key} is too long.')
    for key in DATE_FIELDS:
        if values[key]:
            try: date.fromisoformat(values[key])
            except ValueError: errors.append(f'{key} must be a valid date.')
    descriptions = post.getlist('item_description')
    quantities = post.getlist('item_quantity')
    units = post.getlist('item_unit')
    pallets = post.getlist('item_pallets')
    per_pallet = post.getlist('item_units_per_pallet')
    if max(map(len, (descriptions, quantities, units, pallets, per_pallet)), default=0) > 40:
        errors.append('Maximum 40 line items.')
    items = []
    for i in range(min(40, max(len(descriptions), len(quantities)))):
        desc = (descriptions[i] if i < len(descriptions) else '').strip()
        qty = (quantities[i] if i < len(quantities) else '').strip()
        unit = (units[i] if i < len(units) else '').strip()
        pallet = (pallets[i] if i < len(pallets) else '').strip()
        upp = (per_pallet[i] if i < len(per_pallet) else '').strip()
        if not any((desc, qty, unit, pallet, upp)): continue
        if not desc: errors.append(f'Line {i+1}: description required.'); continue
        if len(desc) > 255 or len(unit) > 40: errors.append(f'Line {i+1}: text too long.')
        try:
            quantity = int(qty) if qty else 0
            p = int(pallet) if pallet else 0
            u = int(upp) if upp else 0
            if quantity < 0 or p < 0 or u < 0 or max(quantity,p,u) > 100000000: raise ValueError
        except ValueError:
            errors.append(f'Line {i+1}: quantities must be nonnegative whole numbers.'); continue
        if quantity == 0 and p and u: quantity = p*u
        items.append(dict(description=desc, quantity=quantity, unit=unit or 'units', pallets=p, units_per_pallet=u))
    if not items: errors.append('Add at least one item.')
    return values, items, errors


def _pdf(company_name, values, items):
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, rightMargin=45, leftMargin=45, topMargin=48, bottomMargin=45)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='MutedOrder', parent=styles['Normal'], textColor=colors.HexColor('#526477'), fontSize=9, leading=14))
    safe = lambda v: escape(str(v or ''))
    story = [Paragraph('PURCHASE ORDER', styles['Title']), Spacer(1, 10), Paragraph(safe(company_name), styles['Heading2']), Spacer(1, 12)]
    pairs = [('Customer', values['customer_name']), ('Destination / Location', values['location_name']),
             ('PO Number', values['po_number']), ('Order Reference / RPC', values['rpc_number']),
             ('Container', values['container_number']), ('Booking', values['booking_number']),
             ('B/L', values['bill_of_lading_number']), ('Owner', values['assigned_to']),
             ('Origin', values['origin_country']), ('Status', values['status']),
             ('Requested', values['requested_date']), ('Loading', values['loading_date']),
             ('ETD', values['etd']), ('ETA', values['eta']), ('Est. Delivery', values['estimated_delivery_date'])]
    rows = []
    for title, value in pairs:
        if value: rows.append([Paragraph(safe(title), styles['MutedOrder']), Paragraph(safe(value), styles['Normal'])])
    info = Table(rows, colWidths=[145, 370], hAlign='LEFT')
    info.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),7),('LINEBELOW',(0,-1),(-1,-1),0.5,colors.HexColor('#d6dfe7'))]))
    story += [info, Spacer(1, 22), Paragraph('Order contents', styles['Heading2']), Spacer(1, 7)]
    itemrows = [[Paragraph(s, styles['Normal']) for s in ('Description','Quantity','Unit','Pallets','Units / pallet')]]
    for line in items:
        itemrows.append([Paragraph(safe(line['description']),styles['Normal']), str(line['quantity']), Paragraph(safe(line['unit']),styles['Normal']), str(line['pallets'] or ''), str(line['units_per_pallet'] or '')])
    table=Table(itemrows,colWidths=[225,80,80,55,75],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf3f8')),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),9),('LINEBELOW',(0,0),(-1,-1),0.35,colors.HexColor('#d8e1e8'))]))
    story.append(table)
    if values['notes']:
        story += [Spacer(1,20),Paragraph('Notes',styles['Heading2']),Paragraph(safe(values['notes']).replace('\n','<br/>'),styles['Normal'])]
    doc.build(story)
    return output.getvalue()


@login_required
@require_http_methods(['GET','POST'])
def generate_new_order_view(request):
    company = _authorized_company(request)
    if request.method == 'GET':
        return render(request, 'core/generate_new_order.html', {'company': company, 'demo_mode': is_demo_user(request.user)})
    values, items, errors = _extract(request.POST)
    if errors:
        return render(request, 'core/generate_new_order.html', {'company':company, 'errors':errors,'values':values,'items':items,'demo_mode':is_demo_user(request.user)},status=400)
    if is_demo_user(request.user):
        created = dict(request.session.get(DEMO_CREATED_KEY, {}))
        if len(created) >= 100:
            return HttpResponse('Demo session order limit reached.',status=400)
        pk = max([DEMO_ID_START-1]+[int(key) for key in created])+1
        created[str(pk)] = dict(values, status=values['status'] or 'Booked')
        request.session[DEMO_CREATED_KEY] = created
        overrides = dict(request.session.get('demo_order_tracker_overrides_v1', {}))
        overrides[str(pk)] = {'lines':[{'item_description':l['description'],'pallets':l['pallets'],'units_per_pallet':l['units_per_pallet'],'total_units':l['quantity']} for l in items]}
        request.session['demo_order_tracker_overrides_v1'] = overrides
        request.session.modified = True
    else:
        with transaction.atomic():
            order_fields = {k:v for k,v in values.items() if k in FIELDS and k not in DATE_FIELDS and k != 'notes'}
            for field in DATE_FIELDS: order_fields[field] = date.fromisoformat(values[field]) if values[field] else None
            order_fields['status'] = values['status'] or 'Booked'
            order = OrderContainer.objects.create(company=company, created_by=request.user, **order_fields, notes=values['notes'])
            OrderContainerLine.objects.bulk_create([OrderContainerLine(container=order,item_description=i['description'],pallets=i['pallets'],units_per_pallet=i['units_per_pallet'],total_units=i['quantity']) for i in items])
    pdf = _pdf('Demo Company' if is_demo_user(request.user) else company.name, values, items)
    response=HttpResponse(pdf, content_type='application/pdf')
    filename = ''.join(ch for ch in (values['po_number'] or 'new-order') if ch.isalnum() or ch in '-_')[:65] or 'new-order'
    response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
    response['Cache-Control'] = 'no-store'
    return response
