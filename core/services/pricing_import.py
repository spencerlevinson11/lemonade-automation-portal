import pandas as pd
import re
from decimal import Decimal
from collections import Counter

PRICE_RE = re.compile(r"[^0-9.\-]+")

def _clean_price(val) -> Decimal | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    s = PRICE_RE.sub("", s)
    if not s:
        return None
    try:
        return Decimal(s)
    except Exception:
        return None


def _infer_customer_destination(labels: list[str]) -> dict[str, tuple[str, str]]:
    """
    Your row labels are like:
      "Elite Miami"
      "Bay State E. Patchogue"
      "Bouquet Collection Joliet"

    Destinations may contain spaces, so splitting on last space fails.
    Instead:
      - discover customer prefixes that appear multiple times
      - choose the longest repeated prefix as customer
      - remainder becomes destination
    """
    tokenized = [(lab, lab.split()) for lab in labels]
    prefix_counts = Counter()

    for _, toks in tokenized:
        for i in range(1, len(toks)):  # prefix must leave at least 1 token for destination
            prefix_counts[" ".join(toks[:i])] += 1

    out = {}
    for lab, toks in tokenized:
        best_prefix = None
        best_len = 0
        for i in range(1, len(toks)):
            pref = " ".join(toks[:i])
            if prefix_counts[pref] >= 2 and i > best_len:
                best_prefix = pref
                best_len = i

        if best_prefix:
            customer = best_prefix
            destination = lab[len(best_prefix):].strip()
        else:
            # fallback if only one destination exists for that customer
            customer = toks[0]
            destination = " ".join(toks[1:]).strip()

        out[lab] = (customer.strip(), destination.strip())
    return out


def parse_pricing_matrix_csv(file_path: str) -> list[dict]:
    """
    Returns a list of dicts:
      { customer, destination, product_description, price_delivered }
    """
    # Your file is commonly exported in Windows-1252
    df = pd.read_csv(file_path, encoding="cp1252")

    # Row 0 has product headers in columns 1..N
    product_headers = {}
    for col in df.columns[1:]:
        header = str(df.loc[0, col]).strip()
        if header and header.lower() != "nan":
            product_headers[col] = header

    # Data rows start at row 2 (row 1 is blank in your file)
    data = df.iloc[2:].copy()

    # First column is the "Customer Destination" label
    first_col = df.columns[0]
    data[first_col] = data[first_col].astype(str).str.strip()
    data = data[data[first_col].str.lower() != "nan"]

    labels = data[first_col].tolist()
    mapping = _infer_customer_destination(labels)

    rows_out = []
    for _, row in data.iterrows():
        label = str(row[first_col]).strip()
        if not label or label.lower() == "nan":
            continue

        customer, destination = mapping.get(label, (label, ""))

        for col, product_desc in product_headers.items():
            price = _clean_price(row.get(col))
            if price is None:
                continue

            rows_out.append({
                "customer": customer,
                "destination": destination,
                "product_description": product_desc,
                "price_delivered": price,
            })

    return rows_out
