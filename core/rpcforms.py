from django import forms

CONTACT_CHOICES = [
    ("spencer", "Spencer"),
    ("jaime", "Jaime"),
]


class RpcOrderForm(forms.Form):
    # --- Header / dates / company info ---

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
    contact_person = forms.ChoiceField(
        label="Send emails to",
        choices=CONTACT_CHOICES,
        initial="spencer",
        widget=forms.Select(attrs={"class": "input"}),
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

    # --- Bucket bank: one numeric field per bucket type ---
    # Leave blank or 0 if not used. Value is "number of pallets".

    # "10 Wide Standard Classic" is ordered in three pallet-quantity variants.
    # These three fields replace the legacy single "10 Wide Standard Classic" input.

    b_10_wide_standard_classic_x_2520 = forms.IntegerField(
        label="10 Wide Standard Classic x 2520",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_10_wide_standard_classic_x_2660 = forms.IntegerField(
        label="10 Wide Standard Classic x 2660",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_10_wide_standard_classic_x_2800 = forms.IntegerField(
        label="10 Wide Standard Classic x 2800",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )

    b_10_liter_classic_n6_plus_2520 = forms.IntegerField(
        label="10 liter classic N6+ 2520",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_10_liter_n6_plus_x_2800 = forms.IntegerField(
        label="10 liter wide N6+ x 2800",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_10_ltr_conical_next_gen = forms.IntegerField(
        label="10 ltr conical Next Gen",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_10_ltr_conical_black = forms.IntegerField(
        label="10 ltr conical black",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_10_ltr_wide_ng_eco = forms.IntegerField(
        label="10 ltr wide NG eco",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_13_ltr_conical_black = forms.IntegerField(
        label="13 ltr conical black",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )

    b_13_ltr_conical_pink = forms.IntegerField(
        label="13 ltr conical pink",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_13_ltr_conical_next_gen = forms.IntegerField(
        label="13 ltr conical Next Gen",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_5_liter_vase = forms.IntegerField(
        label="5 liter vase",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_7_liter_vase = forms.IntegerField(
        label="7 liter vase #",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_5_liter_round = forms.IntegerField(
        label="5 liter round",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_8_liter_round_bucket = forms.IntegerField(
        label="8 liter round bucket",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )

    b_8_liter_wide_nir_grey = forms.IntegerField(
        label="8 liter wide NIR grey",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )

    b_8_liter_round_ng_bucket = forms.IntegerField(
        label="8 liter round NG bucket",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )

    b_3_liter_round_bucket = forms.IntegerField(
        label="3 liter round bucket",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_10_liter_wide_classic_hq = forms.IntegerField(
        label="10 liter wide classic HQ#",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )

    b_10_liter_wide_nir_grey_2520 = forms.IntegerField(
        label="10 liter wide NIR grey 2520",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )

    b_amalia_white_buckets = forms.IntegerField(
        label="Amalia White Buckets",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_amalia_black_buckets = forms.IntegerField(
        label="Amalia Black Buckets",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_amalia_white_lids = forms.IntegerField(
        label="Amalia White Lids",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_amalia_black_lids = forms.IntegerField(
        label="Amalia Black Lids",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_maxima_green_buckets = forms.IntegerField(
        label="Maxima Green Buckets",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_maxima_buckets_white = forms.IntegerField(
        label="Maxima Buckets White",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_maxima_black_buckets = forms.IntegerField(
        label="Maxima Black Buckets",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_maxima_green_lids = forms.IntegerField(
        label="Maxima Green Lids",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_maxima_lids_white = forms.IntegerField(
        label="Maxima Lids White",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )
    b_maxima_black_lids = forms.IntegerField(
        label="Maxima Black Lids",
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "input", "placeholder": "0", "inputmode": "numeric"}
        ),
    )





