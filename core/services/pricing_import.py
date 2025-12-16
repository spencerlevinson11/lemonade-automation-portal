import pandas as pd
import re
from decimal import Decimal
from collections import Counter

PRICE_RE = re.compile(r"[^0-9.\-]+")

# Heuristics to detect a product-header row for a "grid"
HEADER_KEYWORDS = (
    "liter", "bucket", "lid", "maxima", "amalia", "nextgen", "next gen",
    "conical", "classic", "round", "wide"
)

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
    Supports multiple product tables ("blocks") in the same CSV.

    FIXED: Properly handles multiple grids by detecting each header row and
    rebuilding the column->product mapping per grid. This prevents prices in
    the lower grid from being mis-assigned to product headers from the upper grid.
    """
    # Try common encodings (your file is often Windows-1252)
    try:
        df = pd.read_csv(file_path, encoding="cp1252")
    except Exception:
        df = pd.read_csv(file_path, encoding="utf-8", errors="ignore")

    if df.empty:
        return []

    first_col = df.columns[0]

    # Normalize strings for detection
    def norm(x):
        if x is None:
            return ""
        s = str(x).strip()
        return "" if s.lower() in {"nan", "none"} else s

    def _row_text(row) -> str:
        parts = []
        for c in df.columns:
            v = norm(row.get(c))
            if v:
                parts.append(v)
        return " ".join(parts).lower()

    def is_header_row(row) -> bool:
        """
        A header row for a grid is a row that contains multiple product names across columns.
        Previously you required first_col to be blank; that can fail on some exports.
        We now detect headers by:
          - having many non-empty cells in columns 1..N
          - AND containing product-ish keywords somewhere in the row
        """
        nonempty = 0
        for c in df.columns[1:]:
            if norm(row.get(c)):
                nonempty += 1

        if nonempty < 3:
            return False

        text = _row_text(row)
        return any(k in text for k in HEADER_KEYWORDS)

    # A "data row" should have a non-empty first_col label
    def is_data_row(row) -> bool:
        return bool(norm(row.get(first_col)))

    rows_out: list[dict] = []

    # Find all header row indices (start of blocks)
    header_idxs = []
    for i in range(len(df)):
        if is_header_row(df.iloc[i]):
            header_idxs.append(i)

    if not header_idxs:
        # fallback to your original "row 0 is headers" assumption
        header_idxs = [0]

    # Add a sentinel end index
    header_idxs.append(len(df))

    for b in range(len(header_idxs) - 1):
        header_i = header_idxs[b]
        end_i = header_idxs[b + 1]

        header_row = df.iloc[header_i]

        # Map column -> product header text (for this block)
        product_headers = {}
        for col in df.columns[1:]:
            h = norm(header_row.get(col))
            if h:
                product_headers[col] = h

        if not product_headers:
            continue

        # Data rows for this block are ONLY the rows after header_i until end_i
        block_df = df.iloc[header_i + 1: end_i].copy()

        # Build label -> (customer, destination) map within this block
        labels = [norm(x) for x in block_df[first_col].tolist() if norm(x)]
        mapping = _infer_customer_destination(labels) if labels else {}

        # Emit rows for this block
        for _, row in block_df.iterrows():
            label = norm(row.get(first_col))
            if not label:
                # IMPORTANT: do not treat blank-label rows as data; prevents cross-grid misassignment
                continue

            customer, destination = mapping.get(label, (label, ""))

            for col, product_desc in product_headers.items():
                price = _clean_price(row.get(col))
                if price is None:
                    continue

                rows_out.append({
                    "customer": customer.strip(),
                    "destination": destination.strip(),
                    "product_description": product_desc.strip(),
                    "price_delivered": price,
                })

    return rows_out
