# core/forms.py
from django import forms


class BOLForm(forms.Form):
    # These labels mirror your "BOL INFORMATION SHEET" rows

    # Row 1
    shipper_number = forms.CharField(
        label="Shippers #",
        required=False,
        help_text="Internal shipper number (e.g., 48, 50)."
    )

    # Row 2
    carrier = forms.CharField(
        label="Carrier",
        required=False,
    )

    # Row 3
    quote_number = forms.CharField(
        label="Quote #",
        required=False,
    )

    # Row 4
    pro_number = forms.CharField(
        label="PRO #",
        required=False,
    )

    # Row 5
    ship_date = forms.DateField(
        label="Date",
        required=True,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    # Row 6
    po_number = forms.CharField(
        label="PO #",
        required=False,
    )

    # Row 7
    seal_number = forms.CharField(
        label="Seal #",
        required=False,
    )

    # Row 8
    consignee_name = forms.CharField(
        label="Consignee Name",
        required=True,
    )

    # Row 9
    consignee_street_address = forms.CharField(
        label="Consignee Street Address",
        required=True,
    )

    # Row 10
    consignee_city_state_zip = forms.CharField(
        label="Consignee City, State, Zip",
        required=True,
    )

    # Row 11
    attention = forms.CharField(
        label="Attn:",
        required=False,
    )

    # Row 12
    num_pallets = forms.IntegerField(
        label="No. of Pallets",
        required=True,
    )

    # Row 13
    article_description = forms.CharField(
        label="Article Description",
        required=True,
        initial="Plastic Bouquet Buckets",
    )

    # Row 14
    specific_article = forms.CharField(
        label="Specific Article",
        required=True,
        help_text="e.g., 10 liter wide classic buckets",
    )

    # Row 15
    amount_of_article = forms.CharField(
        label="Amount of Article",
        required=True,
        help_text="e.g., (2 x 2660) = 5320 buckets",
    )

    # Row 16
    pallet_dimensions = forms.CharField(
        label="Article Pallet Dimensions",
        required=True,
        help_text="e.g., 2 pallets @ 40 x 45 x 94",
    )

    # Row 17
    weight = forms.CharField(
        label="Weight",
        required=True,
        help_text="e.g., 2100 lbs",
    )

    # Row 18
    freight_class = forms.CharField(
        label="Class",
        required=True,
        help_text="e.g., 92",
    )
