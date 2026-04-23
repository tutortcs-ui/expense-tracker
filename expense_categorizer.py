"""
EXPENSE CATEGORIZER
====================
Categorizes Indian bank UPI/NEFT/ATM transactions from Indian bank statements.

Three-layer approach (in order of priority):
1. Exact + fuzzy keyword match on the UPI note (human-written, most reliable)
2. MCC code lookup (merchant category set by bank)
3. Full text keyword scan (UPI IDs, merchant patterns)
4. Fallback rules (personal UPI + small amount = Food, ATM = cash category)

All matching is case-insensitive.
"""

import re
from difflib import get_close_matches


# ============================================================================
# MCC CODE MAP
# 4-digit merchant category codes at the end of UPI strings e.g. /5411
# ============================================================================

MCC_CATEGORY_MAP = {
    '5411': 'Food',          # Grocery stores
    '5412': 'Food',
    '5441': 'Food',          # Candy / confectionery
    '5451': 'Food',          # Dairy products
    '5499': 'Food',          # Misc food stores
    '5812': 'Food',          # Eating places / restaurants
    '5814': 'Food',          # Fast food
    '5462': 'Food',          # Bakeries
    '5912': 'Medical',       # Drug stores / pharmacies
    '8011': 'Medical',       # Doctors
    '8062': 'Medical',       # Hospitals
    '8099': 'Medical',       # Health practitioners
    '8071': 'Medical',       # Health clubs / fitness
    '5942': 'Books',         # Book stores
    '8299': 'Books',         # Schools / educational
    '5310': 'Shopping',      # Discount stores
    '5311': 'Shopping',      # Department stores
    '5993': 'Shopping',      # Misc retail
    '5817': 'Subscriptions', # Digital goods / software
    '4112': 'Travel',        # Passenger railways
    '4784': 'Travel',        # Tolls / road fees
    '4814': 'Recharge',      # Telecom
    '5331': 'Home',          # Variety stores
    '5211': 'Home',          # Hardware stores
    '5947': 'Home',          # Gift / novelty shops
    '9402': 'Home',          # Postal services
    '7549': 'Tools',         # Towing / auto repair
    '9399': 'Travel',        # Government / postal
    '5262': 'Shopping',      # Women's clothing (Amazon generic MCC)
    '7538': 'Travel',        # Auto service
    '5942': 'Books',
    '0000': None,            # No MCC — rely on keyword matching
}


# ============================================================================
# CATEGORY KEYWORD LISTS
# More specific categories are listed first.
# Within each list, more specific phrases are listed before general words.
# ============================================================================

CATEGORY_KEYWORDS = {

    'Priyanka': [
        'priyanka',
    ],

    'Bank Charges': [
        'chrg/mob', 'mob alert', 'sms alert', 'bank charge',
        'service charge', 'annual charge', 'processing fee', 'chrg/',
    ],

    'Rent': [
        'rent', 'kmc', 'kolkata municipal', 'municipality',
        'maintenance', 'society', 'landlord',
    ],

    'Medical': [
        'medical', 'medicine', 'medicines', 'pharmacy', 'chemist',
        'hospital', 'clinic', 'maternity', 'nursing home',
        'doctor', 'dr.', '/dr', 'drpur', 'dpcto',
        'scan doct', 'scan doc', 'pathology', 'lab test',
        'apollo', 'fortis', 'mosquito', 'sanitizer',
        'pastur',   # Pastur = scan centre name, not milk
    ],

    'Food': [
        # Bengali foods
        'ruti', 'ruit', 'dhosa', 'dhowa', 'lassi', 'malpoa',
        'paan', 'chop',
        # Common food words
        'food', 'grocery', 'groceries', 'groce',
        'vegetable', 'veg', 'sabzi',
        'fruit', 'fruits', 'banana',
        'rice', 'fish', 'meat', 'chicken', 'mutton', 'egg',
        'milk', 'bread', 'curd', 'paneer',
        'snack', 'snacks', 'biscuit',
        'sweet', 'sweets', 'swets', 'mithai',
        'kulfi', 'kulf', 'ice cream', 'icecream', 'icecre',
        'daab', 'coconut', 'cocon',
        'water',
        'restaurant', 'hotel', 'cafe', 'tiffin',
        'lunch', 'dinner', 'breakfast',
        'biryani', 'pizza', 'burger',
        'swiggy', 'zomato', 'blinkit', 'zepto', 'dunzo',
        'refill',
        # Merchant UPI IDs seen in data
        'paytmqr6r1d2z', 'paytmqr6wz4mo', 'paytmqr6qllxp',
        'paytmqr6vyzn5', 'paytmqr6hkyi6', 'paytmqr726h5n',
        'q983545028', 'q982324791', 'q222457382', 'q544422605',
        'q491850880', 'q306274145', 'q81684614', 'q017048568',
        'q353324462', 'q344093743', 'q190021426', 'q348173810',
        'q467936681', 'q903203103', 'q974257537', 'q024080582',
        'q060338555', 'q505344652', 'q244567670', 'q506824648',
        'q669543068', 'gpay-12190525019', 'gpay-11244605008',
        'paytm.s10lez0', 'paytm.s1p3egp',
        'hoogafarmspriva', 'ppqr01.rldijp',
    ],

    'Travel': [
        'travel', 'trave', 'train', 'trai', 'railway', 'irctc',
        'metro', 'bus', 'taxi', 'cab', 'ola', 'uber', 'rapido',
        'petrol', 'fuel', 'diesel', 'parking', 'toll',
        'airport', 'flight', 'redbus', 'makemytrip', 'goibibo',
        'bike', 'car',
        'bdpg.iruts', 'bdpg2.iruts',
        'paytm-8727353',
        'gorangadas',
        'paytm.s1g5axt',
    ],

    'Books': [
        'book', 'books', 'notebook', 'stationery',
        'study', 'course', 'education', 'tuition', 'coaching',
        'udemy', 'coursera', 'yssofindia',
    ],

    'Clothes': [
        'cloth', 'clothes', 'clothing', 'shirt', 'pant', 'pants',
        'trouser', 'saree', 'kurta', 'dress', 'fashion', 'garment',
        'textile', 'tailor', 'stitching',
    ],

    'Shopping': [
        'flipkart', 'flip kart', 'meesho', 'raz*meesho',
        'myntra', 'nykaa', 'ajio', 'snapdeal', 'shopsy',
        'raz*', 'instamart', 'hostinger',
        # amazon@rapl is caught by note keywords (books/notebook/clothes)
        # so amazon alone falls here as generic shopping
        'amazon',
    ],

    'Home': [
        'fan cov', 'fan',
        'cutlery', 'soap', 'detergent', 'utensil', 'kitchen',
        'vessel', 'broom', 'mop', 'bucket',
        'household', 'furniture', 'mattress', 'pillow', 'bedsheet',
        'curtain', 'mug', 'bottle',
        'gas ', 'cylinder', 'lpg',
        'electricity', 'water bill', 'wifi', 'broadband',
        'post of',
    ],

    'Tools': [
        'tool', 'tools', 'hardware',
        'repair', 'repai', 'service center',
        'mechanic', 'plumber', 'electrician', 'carpenter',
        'bag repai', 'mobile repair', 'screen repair', 'spare',
        'car to sc',
    ],

    'Garden': [
        'garden', 'plant', 'nursery', 'seed', 'fertilizer', 'pot', 'soil',
    ],

    'Recharge': [
        'recharge', 'gpayrecharge', 'gpay recharge',
        'mobile', 'mobi', 'phon', 'phone',
        'dth', 'airtel', 'jio', 'bsnl', 'vodafone',
        'internet', 'postpaid', 'prepaid',
        'lakshman.kamila', 'paytm.s19shw9',
    ],

    'Subscriptions': [
        'netflix', 'amazon prime', 'hotstar', 'disney', 'spotify',
        'youtube', 'playstore', 'play store', 'subscription',
        'membership', 'manda', 'playstore@axisbank',
    ],

    'Gifts': [
        'gift', 'donation', 'charity', 'temple', 'pooja', 'puja',
    ],

    'Wages': [
        'wages', 'wage', 'salary', 'worker', 'maid', 'cook',
        'driver', 'helper', 'staff',
    ],

    'Finance': [
        'loan rep', 'loan', 'emi ', 'insurance', 'premium',
        'mutual fund', 'sip', 'fixed deposit', 'nps', 'ppf',
    ],

    'Transfers': [
        'neft', 'imps', 'ft imps', 'rtgs',
        'nilima', 'biman', 'paytm-8746350',
    ],
}


# ============================================================================
# FUZZY MATCHING SETUP
# Build a flat keyword→category map for close-match lookups.
# Only words 4+ characters are included to avoid false positives.
# ============================================================================

_FUZZY_KEYWORDS = []
_FUZZY_KEYWORD_TO_CAT = {}

for _cat, _words in CATEGORY_KEYWORDS.items():
    for _w in _words:
        if len(_w) >= 4 and '@' not in _w and '/' not in _w and '.' not in _w:
            _FUZZY_KEYWORDS.append(_w)
            _FUZZY_KEYWORD_TO_CAT[_w] = _cat


# ============================================================================
# MERCHANT DETECTION
# These UPI ID patterns belong to payment gateways, not individuals.
# Personal UPIs (names / phone numbers) are everything else.
# ============================================================================

_MERCHANT_PATTERNS = [
    'paytmqr', 'paytm.', 'bharatpe.', 'gpay-', 'gpayrecharge',
    'amazon', 'flipkart', 'razorpay', 'rzp@', 'postbank',
    'ppqr', 'ptybl', 'ptyes', 'iservuqrs', 'okbizax',
    'okpayaxis', 'naviaxis', 'rldijp', 'hostinger',
    'yssofindia', 'getepay', 'cmcltd', 'bpunity',
]

# Notes that carry no useful information
_USELESS_NOTES = {
    'upi', '0000', 'up', 'f', 't', 'mi', 'sw', 'cu', '',
    'sent', 'pay', 'na', 'n/a',
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def clean_numeric_value(value):
    """Convert a bank amount string like '1,234.56' to float. Returns 0.0 for blanks."""
    if value is None:
        return 0.0
    s = str(value).strip()
    if s in ['', 'nan', 'NaN', '-']:
        return 0.0
    try:
        return float(s.replace(',', ''))
    except ValueError:
        return 0.0


def clean_date(value):
    """Parse a date value into a pandas Timestamp. Returns NaT if unparseable."""
    import pandas as pd
    try:
        return pd.to_datetime(str(value), dayfirst=True)
    except Exception:
        return pd.NaT


def _extract_mcc(text):
    """Extract the 4-digit MCC code from the end of a UPI string."""
    match = re.search(r'/(\d{4})$', text.strip())
    return match.group(1) if match else None


def _get_upi_parts(text):
    """
    Split a UPI string into (upi_id, note).
    UPI format: UPIOUT/txnid/upi_id@bank/note/MCC
    """
    parts = text.split('/')
    upi_id = parts[2].strip() if len(parts) > 2 else ''
    note   = parts[3].strip().lower() if len(parts) > 3 else ''
    return upi_id, note


def _is_merchant_upi(upi_id):
    """Return True if this UPI ID belongs to a payment gateway or merchant."""
    uid = upi_id.lower()
    return any(m in uid for m in _MERCHANT_PATTERNS)


def _fuzzy_match_note(note):
    """
    Return category if note is close enough to a known keyword.
    Uses 78% similarity threshold — catches spelling mistakes like
    'poants'→'pants', 'icecre'→'icecream', 'groce'→'grocery'.
    Returns None if no confident match.
    """
    if not note or len(note) < 3:
        return None
    matches = get_close_matches(note, _FUZZY_KEYWORDS, n=1, cutoff=0.78)
    if matches:
        return _FUZZY_KEYWORD_TO_CAT[matches[0]]
    return None


# ============================================================================
# MAIN CATEGORIZER
# ============================================================================

def categorize_transaction(particulars, tran_type='Unknown', amount=0):
    """
    Determine the spending category for a single bank transaction.

    Priority order:
    1. Bank charges (by text pattern)
    2. ATM withdrawals → amount-based cash category
    3. UPI note — exact keyword match (most reliable human signal)
    4. UPI note — fuzzy match (catches spelling mistakes)
    5. MCC code lookup (merchant category from bank)
    6. Full Particulars text keyword scan
    7. Personal UPI + amount < ₹100 + useless note → Food
    8. Transfer-type transactions → Transfers
    9. Fallback → Miscellaneous

    Args:
        particulars: Transaction description from the bank statement
        tran_type:   Transaction type e.g. 'UPI', 'ATM', 'NEFT', 'TFR'
        amount:      Transaction amount (float) — used for ATM and food rules

    Returns:
        str: Category name
    """
    if not particulars or str(particulars).strip() == '':
        return 'Miscellaneous'

    text  = str(particulars).lower().strip()
    tran  = str(tran_type).lower().strip()
    amt   = float(amount) if amount else 0.0

    # ── 1. Bank charges ───────────────────────────────────────────────────────
    if 'chrg/' in text or 'mob alert' in text:
        return 'Bank Charges'

    # ── 2. ATM withdrawals — amount tells us what the cash was for ────────────
    if tran == 'atm' or text.startswith('to atm/'):
        if amt >= 2000:
            return 'Family Cash'
        return 'Cash Withdrawal'

    # ── 3 & 4. Extract UPI note and try keyword + fuzzy matching ─────────────
    upi_id, note = _get_upi_parts(text)

    if note and note not in _USELESS_NOTES:
        # Exact keyword match on note first
        for category, keywords in CATEGORY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in note:
                    return category
        # Fuzzy match — catches spelling mistakes
        fuzzy = _fuzzy_match_note(note)
        if fuzzy:
            return fuzzy

    # ── 5. MCC code lookup ────────────────────────────────────────────────────
    mcc = _extract_mcc(text)
    if mcc and mcc in MCC_CATEGORY_MAP and MCC_CATEGORY_MAP[mcc] is not None:
        # Only trust MCC when note was useless or absent
        # (note already ran above and didn't match — MCC is our next best signal)
        mcc_cat = MCC_CATEGORY_MAP[mcc]
        if mcc != '0000':
            return mcc_cat

    # ── 6. Full text keyword scan (UPI IDs, merchant names) ──────────────────
    is_transfer_type = (
        tran in ['neft', 'imps', 'rtgs'] or
        'ft imps' in text or
        text.startswith('nft/')
    )

    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                return category

    # ── 7. Personal UPI + tiny amount + no useful note → Food ────────────────
    # Rule: when you send ₹15–₹99 to a person with no note,
    # it is almost always a small food purchase (street vendor, etc.)
    if not _is_merchant_upi(upi_id) and note in _USELESS_NOTES and amt < 100:
        return 'Food'

    # ── 8. Transfer-type with no keyword match ────────────────────────────────
    if is_transfer_type:
        return 'Transfers'

    return 'Miscellaneous'
