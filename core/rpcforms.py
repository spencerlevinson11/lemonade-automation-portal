from django import forms


class RpcOrderForm(forms.Form):
    po = forms.CharField(
        label="Customer PO#",
        max_length=100,
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    rpc_info = forms.CharField(
        label="RPC number",
        max_length=50,
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    nld = forms.DateField(
        label="Preferred pickup (NLD)",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "input"}),
    )
    delivery = forms.DateField(
        label="Delivery date",
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "input"}),
    )

    company = forms.CharField(
        label="Company name",
        max_length=255,
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    city_state = forms.CharField(
        label="City & state",
        max_length=255,
        widget=forms.TextInput(attrs={"class": "input"}),
    )

    addr_line1 = forms.CharField(
        label="Address line 1",
        max_length=255,
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    addr_line2 = forms.CharField(
        label="Address line 2",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    addr_line3 = forms.CharField(
        label="Address line 3",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    addr_line4 = forms.CharField(
        label="Address line 4",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "input"}),
    )
    addr_line5 = forms.CharField(
        label="Address line 5",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "input"}),
    )

    denkers = forms.BooleanField(
        label="Send Denkers email as well",
        required=False,
    )

    bucket_lines = forms.CharField(
        label="Buckets & pallet counts",
        help_text=(
            "One per line, for example:<br>"
            "<code>10 ltr conical Next Gen: 12</code><br>"
            "<code>Maxima Black Buckets: 3</code>"
        ),
        widget=forms.Textarea(
            attrs={
                "rows": 8,
                "class": "input",
                "style": "font-family: monospace;",
            }
        ),
    )
