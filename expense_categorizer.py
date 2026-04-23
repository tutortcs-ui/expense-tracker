"""
EXPENSE CATEGORIZER
====================
10 fixed categories for personal expense tracking.

Categories:
  1. Rent             — recurring bank transfers (NEFT/IMPS) to landlord
  2. Family           — ATM Rs2000-5000, personal transfers to family
  3. Food             — groceries, restaurants, street food, ATM under Rs1000
  4. Travel           — train, petrol, bus, cab, bike
  5. Medical          — doctors, pharmacy, hospital, scan, back-to-back ATM>5000
  6. Subscriptions & Devices — mobile, internet, streaming, apps, phone repair, devices
  7. Books            — books, stationery, education, courses
  8. Garden           — plants, nursery, garden wages
  9. Gifts            — gifts, donations, charity
 10. Miscellaneous    — clothes, home, shopping, everything else

Categorization priority:
  1. Bank charges pattern → Subscriptions & Devices
  2. ATM amount rules
  3. UPI note exact match
  4. UPI note fuzzy match (catches spelling mistakes)
  5. MCC code lookup
  6. Full text keyword scan
  7. Personal UPI + under Rs100 + blank note → Food
  8. NEFT/IMPS recurring → Rent
  9. Fallback → Miscellaneous
"""

import re
from difflib import get_close_matches


# ============================================================================
# MCC CODE MAP
# ============================================================================

MCC_CATEGORY_MAP = {
    '5411': 'Food',
    '5412': 'Food',
    '5441': 'Food',
    '5451': 'Food',
    '5499': 'Food',
    '5812': 'Food',
    '5814': 'Food',
    '5462': 'Food',
    '5912': 'Medical',
    '8011': 'Medical',
    '8062': 'Medical',
    '8099': 'Medical',
    '8071': 'Medical',
    '5942': 'Books',
    '8299': 'Books',
    '5310': 'Miscellaneous',
    '5311': 'Miscellaneous',
    '5993': 'Miscellaneous',
    '5817': 'Subscriptions & Devices',
    '4112': 'Travel',
    '4784': 'Travel',
    '4814': 'Subscriptions & Devices',
    '5331': 'Miscellaneous',
    '5211': 'Miscellaneous',
    '5947': 'Miscellaneous',
    '9402': 'Miscellaneous',
    '7549': 'Subscriptions & Devices',  # device/phone repair
    '9399': 'Travel',
    '5262': 'Miscellaneous',
    '7538': 'Travel',
    '0000': None,
}


# ============================================================================
# CATEGORY KEYWORD LISTS
# ============================================================================

CATEGORY_KEYWORDS = {

    'Rent': [
        'rent', 'landlord',
        'kmc', 'kolkata municipal', 'municipality',
        'maintenance', 'society',
    ],

    'Family': [
        'family',
    ],

    'Medical': [
        'medical', 'medicine', 'medicines', 'pharmacy', 'chemist',
        'hospital', 'clinic', 'maternity', 'nursing home',
        'doctor', 'dr.', '/dr', 'drpur', 'dpcto',
        'scan doct', 'scan doc', 'pastur',
        'pathology', 'lab test', 'apollo', 'fortis',
        'mosquito', 'sanitizer',
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
        'water', 'refill',
        'restaurant', 'hotel', 'cafe', 'tiffin',
        'lunch', 'dinner', 'breakfast',
        'biryani', 'pizza', 'burger',
        'swiggy', 'zomato', 'blinkit', 'zepto', 'dunzo',
        # Known food merchant UPI IDs from data
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
        'paytm-8727353', 'gorangadas', 'paytm.s1g5axt',
    ],

    'Subscriptions & Devices': [
        # Streaming and apps
        'netflix', 'hotstar', 'disney', 'spotify',
        'youtube', 'playstore', 'play store',
        'subscription', 'membership', 'manda',
        'playstore@axisbank',
        # Mobile and internet
        'recharge', 'gpayrecharge', 'gpay recharge',
        'mobile', 'mobi', 'phone', 'phon',
        'dth', 'airtel', 'jio', 'bsnl', 'vodafone',
        'internet', 'postpaid', 'prepaid',
        # Device repair and purchases — only digital/phone devices
        'phone repair', 'mobile repair', 'screen repair',
        'laptop', 'tablet', 'headphone', 'charger', 'cable',
        'device', 'gadget', 'hostinger',
        # Bank charges absorbed here
        'chrg/', 'chrg/mob', 'mob alert', 'sms alert',
        'bank charge', 'service charge', 'annual charge',
        # Known merchant UPI IDs
        'lakshman.kamila', 'paytm.s19shw9',
    ],

    'Books': [
        'book', 'books', 'notebook', 'stationery',
        'study', 'course', 'education', 'tuition', 'coaching',
        'udemy', 'coursera', 'yssofindia',
    ],

    'Garden': [
        'garden', 'plant', 'nursery', 'seed',
        'fertilizer', 'pot', 'soil',
        'wages', 'wage', 'gardener',
    ],

    'Gifts': [
        'gift', 'donation', 'charity', 'temple', 'pooja', 'puja',
        'tithe',
    ],

    'Miscellaneous': [
        # Clothes
        'cloth', 'clothes', 'clothing', 'shirt', 'pant', 'pants',
        'trouser', 'saree', 'kurta', 'dress', 'fashion',
        'garment', 'textile', 'tailor', 'stitching',
        # Home and utilities
        'fan cov', 'fan', 'cutlery', 'soap', 'detergent',
        'utensil', 'kitchen', 'vessel', 'broom', 'mop',
        'bucket', 'household', 'furniture', 'mattress',
        'pillow', 'bedsheet', 'curtain', 'mug', 'bottle',
        'gas ', 'cylinder', 'lpg',
        'electricity', 'water bill', 'wifi', 'broadband',
        'post of', 'kmc', 'kolkata municipal', 'municipality',
        'maintenance', 'society',
        # Repairs (non-device)
        'bag repai', 'bag repair', 'bike repair', 'biie repa',
        'repair', 'repai',
        # Shopping
        'flipkart', 'flip kart', 'meesho', 'raz*meesho',
        'myntra', 'nykaa', 'ajio', 'snapdeal', 'shopsy',
        'raz*', 'instamart', 'amazon',
        # Finance
        'loan rep', 'loan', 'emi ', 'insurance', 'premium',
        'mutual fund', 'sip', 'fixed deposit', 'nps', 'ppf',
    ],
}


# ============================================================================
# FUZZY MATCHING SETUP
# Only words 4+ chars, no UPI IDs or special chars
# ============================================================================

_FUZZY_KEYWORDS = []
_FUZZY_KEYWORD_TO_CAT = {}

for _cat, _words in CATEGORY_KEYWORDS.items():
    for _w in _words:
        if len(_w) >= 4 and '@' not in _w and '/' not in _w and '.' not in _w and '*' not in _w:
            _FUZZY_KEYWORDS.append(_w)
            _FUZZY_KEYWORD_TO_CAT[_w] = _cat


# ============================================================================
# MERCHANT VS PERSONAL UPI DETECTION
# ============================================================================

_MERCHANT_PATTERNS = [
    'paytmqr', 'paytm.', 'bharatpe.', 'gpay-', 'gpayrecharge',
    'amazon', 'flipkart', 'razorpay', 'rzp@', 'postbank',
    'ppqr', 'ptybl', 'ptyes', 'iservuqrs', 'okbizax',
    'okpayaxis', 'naviaxis', 'rldijp', 'hostinger',
    'yssofindia', 'getepay', 'cmcltd', 'bpunity',
    'playstore', 'netflix', 'spotify',
]

_USELESS_NOTES = {
    'upi', '0000', 'up', 'f', 't', 'mi', 'sw', 'cu', '',
    'sent', 'pay', 'na', 'n/a',
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def clean_numeric_value(value):
    """Convert bank amount string like '1,234.56' to float. Returns 0.0 for blanks."""
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
    """Parse date into pandas Timestamp. Returns NaT if unparseable."""
    import pandas as pd
    try:
        return pd.to_datetime(str(value), dayfirst=True)
    except Exception:
        return pd.NaT


def _extract_mcc(text):
    """Extract 4-digit MCC code from end of UPI string."""
    match = re.search(r'/(\d{4})$', text.strip())
    return match.group(1) if match else None


def _get_upi_parts(text):
    """Split UPI string into (upi_id, note)."""
    parts = text.split('/')
    upi_id = parts[2].strip() if len(parts) > 2 else ''
    note   = parts[3].strip().lower() if len(parts) > 3 else ''
    return upi_id, note


def _is_merchant_upi(upi_id):
    """Return True if UPI ID belongs to a payment gateway or merchant."""
    uid = upi_id.lower()
    return any(m in uid for m in _MERCHANT_PATTERNS)


def _fuzzy_match_note(note):
    """
    Return category if note is close enough to a known keyword (78% similarity).
    Catches spelling mistakes: 'poants'→Clothes, 'icecre'→Food, 'groce'→Food.
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
    Categorize a single bank transaction into one of 10 fixed categories.

    Priority order:
      1. Bank charges / SMS alerts → Subscriptions & Devices
      2. ATM amount rules:
           under Rs1000          → Food
           Rs1000–Rs1999         → Miscellaneous
           Rs2000–Rs5000         → Family
           above Rs5000          → Medical (back-to-back same-day rule)
      3. UPI note exact keyword match
      4. UPI note fuzzy match (spelling mistakes)
      5. MCC code lookup
      6. Full text keyword scan
      7. Personal UPI + amount under Rs100 + blank note → Food
      8. NEFT/IMPS with no other match → Rent
      9. Fallback → Miscellaneous

    Args:
        particulars : Transaction description string from bank statement
        tran_type   : Transaction type e.g. 'UPI', 'ATM', 'NEFT', 'TFR'
        amount      : Transaction amount as float

    Returns:
        str: One of the 10 category names
    """
    if not particulars or str(particulars).strip() == '':
        return 'Miscellaneous'

    text = str(particulars).lower().strip()
    tran = str(tran_type).lower().strip()
    amt  = float(amount) if amount else 0.0

    # ── 1. Bank charges / SMS alerts ─────────────────────────────────────────
    if 'chrg/' in text or 'mob alert' in text:
        return 'Subscriptions & Devices'

    # ── 2. ATM withdrawals — amount tells us the purpose ─────────────────────
    if tran == 'atm' or text.startswith('to atm/'):
        if amt < 1000:
            return 'Food'
        elif amt < 2000:
            return 'Miscellaneous'
        elif amt <= 5000:
            return 'Family'
        else:
            # Above Rs5000 — likely medical or special purpose
            # Stage 4 will ask user; for now → Miscellaneous
            return 'Miscellaneous'

    # ── 3 & 4. Extract UPI note → exact then fuzzy keyword match ─────────────
    upi_id, note = _get_upi_parts(text)

    if note and note not in _USELESS_NOTES:
        # Exact match on note first
        for category, keywords in CATEGORY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in note:
                    return category
        # Fuzzy match — catches spelling mistakes like 'poants' → 'pants'
        fuzzy = _fuzzy_match_note(note)
        if fuzzy:
            return fuzzy

    # ── 5. MCC code lookup — only when note gave no signal ───────────────────
    # If note was present but matched nothing, MCC is next best signal.
    # Exception: if note is 'sent', 'u', 'upi' etc. AND merchant is paytm transfer
    # then MCC 4814 (telecom) is misleading — skip it.
    mcc = _extract_mcc(text)
    skip_mcc = (
        mcc == '4814' and
        note in _USELESS_NOTES and
        'paytm-8746350' in text  # known generic money-sender, not telecom
    )
    if not skip_mcc and mcc and mcc in MCC_CATEGORY_MAP and MCC_CATEGORY_MAP[mcc] is not None:
        if mcc != '0000':
            return MCC_CATEGORY_MAP[mcc]

    # ── 6. Full text keyword scan ─────────────────────────────────────────────
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
    if not _is_merchant_upi(upi_id) and note in _USELESS_NOTES and amt < 100:
        return 'Food'

    # ── 8. NEFT/IMPS with no keyword match → Rent ────────────────────────────
    if is_transfer_type:
        return 'Rent'

    return 'Miscellaneous'
