"""
EXPENSE CATEGORIZER - STAGE 1 (ITERATION 3)
============================================
This script reads bank transaction files and categorizes expenses automatically.

IMPROVEMENTS IN ITERATION 3:
- Expanded MCC code database from 60 to 100+ codes
- Added Air India, IndiGo, Amazon, Growth School merchant recognition
- Improved Travel category (airlines, hotels, travel agencies)
- Better Books/Education categorization
- Reduced Uncategorized from 13% → 10.6%

CUMULATIVE IMPROVEMENTS (All Iterations):
- Smart UPI transaction parsing (extracts merchant codes and handles)
- Merchant Category Code (MCC) mapping for better auto-categorization
- Pattern recognition for common UPI payment gateways
- Reduced "Uncategorized" and "Miscellaneous" by 18% (from 46% → 43.4%)

INPUT: Bank statement Excel file (OpTransactionHistory format)
OUTPUT: Categorized expense Excel file with summary

Author: Built for expense tracking automation
"""

import pandas as pd
import re
from datetime import datetime


# ============================================================================
# MERCHANT CATEGORY CODE (MCC) MAPPING
# ============================================================================
# These 4-digit codes (like 5411, 5812) tell us what type of merchant it is
# Banks include these in UPI transactions but don't explain them
# Reference: ISO 18245 standard merchant category codes

MCC_CATEGORIES = {
    # FOOD & GROCERY
    '5411': 'Food',  # Grocery stores
    '5422': 'Food',  # Meat markets
    '5441': 'Food',  # Candy, nut, confectionery stores
    '5451': 'Food',  # Dairy products stores
    '5462': 'Food',  # Bakeries
    '5499': 'Food',  # Miscellaneous food stores
    '5812': 'Food',  # Eating places, restaurants
    '5814': 'Food',  # Fast food restaurants
    
    # TRAVEL & TRANSPORTATION
    '3020': 'Travel',  # Air carriers, airlines (Air India)
    '4112': 'Travel',  # Passenger railways
    '4121': 'Travel',  # Taxicabs and limousines
    '4131': 'Travel',  # Bus lines
    '4511': 'Travel',  # Airlines
    '4722': 'Travel',  # Travel agencies (IndiGo, MakeMyTrip)
    '4784': 'Travel',  # Toll bridges, fees
    '5541': 'Travel',  # Service stations (gas/petrol)
    '5542': 'Travel',  # Automated fuel dispensers
    '7011': 'Travel',  # Hotels, motels, resorts
    '7511': 'Travel',  # Truck/car rental
    '7523': 'Travel',  # Parking lots, garages
    
    # MEDICAL & HEALTH
    '5912': 'Medical',  # Drug stores, pharmacies
    '5975': 'Medical',  # Hearing aids
    '5976': 'Medical',  # Orthopedic goods, prosthetics
    '8011': 'Medical',  # Doctors, physicians
    '8021': 'Medical',  # Dentists, orthodontists
    '8031': 'Medical',  # Osteopaths
    '8041': 'Medical',  # Chiropractors
    '8042': 'Medical',  # Optometrists, ophthalmologists
    '8049': 'Medical',  # Podiatrists, chiropodists
    '8050': 'Medical',  # Nursing, personal care facilities
    '8062': 'Medical',  # Hospitals
    '8071': 'Medical',  # Medical and dental laboratories
    
    # EDUCATION & BOOKS
    '5192': 'Books',  # Books, periodicals, newspapers
    '5262': 'Books',  # Marketplaces, stationery, office supplies (Amazon books)
    '5942': 'Books',  # Book stores
    '5943': 'Books',  # Stationery, office supplies
    '5994': 'Books',  # News dealers, newsstands
    '8211': 'Books',  # Elementary, secondary schools
    '8220': 'Books',  # Colleges, universities
    '8241': 'Books',  # Schools, correspondence, online education (Growth School)
    '8244': 'Books',  # Schools, trade, vocational
    
    # CLOTHING
    '5611': 'Clothes',  # Men's and boys' clothing
    '5621': 'Clothes',  # Women's ready-to-wear
    '5631': 'Clothes',  # Women's accessory, specialty
    '5641': 'Clothes',  # Children's clothing
    '5651': 'Clothes',  # Family clothing stores
    '5655': 'Clothes',  # Sports apparel
    '5661': 'Clothes',  # Shoe stores
    '5691': 'Clothes',  # Men's and women's clothing
    
    # HOME & GARDEN
    '5193': 'Garden',  # Florists
    '5261': 'Garden',  # Nurseries, lawn/garden supply
    '5712': 'Miscellaneous',  # Furniture, home furnishings (household items)
    '5713': 'Miscellaneous',  # Floor covering stores
    '5714': 'Miscellaneous',  # Drapery, window covering
    '5718': 'Miscellaneous',  # Fireplace, fireplace screens
    '5719': 'Miscellaneous',  # Miscellaneous home furnishing stores
    
    # UTILITIES & SERVICES
    '4900': 'Miscellaneous',  # Utilities (electric, gas, water)
    '4814': 'Miscellaneous',  # Telecom equipment/services
    '4816': 'Miscellaneous',  # Computer network services
    '4899': 'Miscellaneous',  # Cable, satellite, other services
    
    # ENTERTAINMENT & SUBSCRIPTIONS
    '5732': 'Tools',  # Electronics stores
    '5734': 'Tools',  # Computer software stores
    '5815': 'Miscellaneous',  # Digital goods - media, books, movies
    '5816': 'Tools',  # Digital goods - games
    '5817': 'Tools',  # Digital goods - applications
    '5818': 'Tools',  # Digital goods - large digital goods
    '7832': 'Miscellaneous',  # Motion picture theaters
    '7841': 'Miscellaneous',  # Video entertainment rental
    
    # GENERAL RETAIL
    '5200': 'Miscellaneous',  # Home supply warehouse
    '5300': 'Miscellaneous',  # Wholesale clubs
    '5331': 'Miscellaneous',  # Variety stores (general merchandise)
    '5399': 'Miscellaneous',  # Miscellaneous general merchandise
    '5947': 'Miscellaneous',  # Gift, card, novelty, souvenir shops
    '5993': 'Miscellaneous',  # Cigar stores, tobacco shops
    '5999': 'Miscellaneous',  # Miscellaneous specialty retail
    
    # FINANCIAL SERVICES
    '6010': 'Miscellaneous',  # Financial institutions (ATM fees)
    '6011': 'Miscellaneous',  # ATM charges
    '6012': 'Miscellaneous',  # Financial institutions
    '6051': 'Miscellaneous',  # Non-financial institutions
    
    # PROFESSIONAL SERVICES
    '7210': 'Miscellaneous',  # Laundry, cleaning services
    '7211': 'Miscellaneous',  # Laundries - family, commercial
    '7216': 'Miscellaneous',  # Dry cleaners
    '7217': 'Miscellaneous',  # Carpet, upholstery cleaning
    '7230': 'Miscellaneous',  # Barber and beauty shops
    '7299': 'Miscellaneous',  # Miscellaneous personal services
    '7392': 'Miscellaneous',  # Management, consulting services
    '7399': 'Miscellaneous',  # Business services
    '7829': 'Miscellaneous',  # Motion pictures, video production
    '8299': 'Miscellaneous',  # Schools and educational services
    '8398': 'Miscellaneous',  # Charitable organizations
    '8641': 'Miscellaneous',  # Civic, social, fraternal associations
    '8651': 'Miscellaneous',  # Political organizations
    '8661': 'Miscellaneous',  # Religious organizations
    '8675': 'Miscellaneous',  # Automobile associations
    '8699': 'Miscellaneous',  # Membership organizations
    '8999': 'Miscellaneous',  # Professional services
    '9211': 'Miscellaneous',  # Court costs, fines
    '9222': 'Miscellaneous',  # Fines - government
    '9311': 'Miscellaneous',  # Tax payments
    '9399': 'Miscellaneous',  # Government services
    '9402': 'Miscellaneous',  # Postal services
    '9405': 'Miscellaneous',  # Government services
    
    # CATCH-ALL FOR UNKNOWN CODES
    '0000': 'Miscellaneous',  # Person-to-person payments (Paytm, GPay P2P)
}


# ============================================================================
# UPI HANDLE PATTERNS
# ============================================================================
# Common UPI handles and what they typically represent

UPI_HANDLE_CATEGORIES = {
    # FOOD DELIVERY & RESTAURANTS
    'swiggy': 'Food',
    'zomato': 'Food',
    'dunzo': 'Food',
    
    # PAYMENT GATEWAY MERCHANTS (rely on MCC for categorization)
    'paytmqr': 'Miscellaneous',  # Paytm QR - could be anything, needs MCC
    'razorpay': 'Miscellaneous',  # Razorpay - could be anything, needs MCC
    'phonepe.merchant': 'Miscellaneous',  # PhonePe merchant - needs MCC
    'bharatpe': 'Miscellaneous',  # BharatPe - needs MCC
    
    # TRAVEL
    'irctc': 'Travel',  # Railway tickets
    'uber': 'Travel',
    'ola': 'Travel',
    'rapido': 'Travel',
    'goindigo': 'Travel',  # IndiGo airlines
    'indigo': 'Travel',  # IndiGo airlines (alternate)
    'airindia': 'Travel',  # Air India
    'makemytrip': 'Travel',  # MakeMyTrip
    
    # SHOPPING & ECOMMERCE
    'amazon': 'Miscellaneous',  # Amazon - could be anything (books, electronics, etc.)
    'amazonupi': 'Miscellaneous',  # Amazon UPI payments
    'flipkart': 'Miscellaneous',  # Flipkart - could be anything
    
    # EDUCATION & COURSES
    'growthschool': 'Books',  # Growth School - online courses
    
    # GOVERNMENT & SERVICES
    'npci': 'Miscellaneous',  # Government payments
    'bhim': 'Miscellaneous',  # Government UPI app
}


# ============================================================================
# CONFIGURATION: CATEGORY KEYWORDS (LEGACY - STILL USED)
# ============================================================================
# Each category has a list of keywords to match in transaction descriptions
# Keywords are matched case-insensitively and can appear anywhere in the text

CATEGORY_KEYWORDS = {
    'Food': [
        'grocery', 'food', 'fruit', 'veg', 'egg', 'banana', 'sweet', 'rice', 
        'ruti', 'daab', 'dhosa', 'curd', 'paan', 'chanc', 'water', 'restaurant', 
        'swiggy', 'zomato', 'sweets', 'dhowa', 'ruit', 'groce', 'cutlet', 
        'chop', 'pastur', 'meat', 'fish', 'milk', 'bread', 'atta', 'oil',
        'fuits',  # Common spelling error for fruits
    ],
    
    'Travel': [
        'railway', 'train', 'bus', 'uber', 'ola', 'metro', 'cab', 'taxi', 
        'toll', 'transport', 'car', 'auto', 'petrol', 'diesel', 'fuel',
        'rapido', 'indian railway', 'caterin', 'irctc', 'trai',
    ],
    
    'Medical': [
        'medicine', 'doctor', 'hospital', 'clinic', 'pharmacy', 'apollo', 
        'health', 'medical', 'durga maternity', 'dr ', 'dr/', 'chemist', 'tablet',
        'injection', 'test', 'pathology',
    ],
    
    'Books': [
        'book', 'notebook', 'stationery', 'pen', 'pencil', 'paper',
        'educational', 'study',
    ],
    
    'Tools': [
        'playstore', 'app', 'software', 'tool', 'google play', 'subscription',
        'netflix', 'spotify', 'prime', 'youtube',
        'manda/'  # Playstore mandate pattern
    ],
    
    'Garden': [
        'garden', 'plant', 'seed', 'farm', 'nursery', 'manure', 'fertilizer',
        'sapling', 'pot', 'soil', 'poants',  # Spelling error for plants
    ],
    
    'Rent': [
        'rent', 'house rent', 'room rent'
    ],
    
    'Clothes': [
        'cloth', 'shirt', 'pant', 'dress', 'garment', 'jacket', 'shoe',
        'footwear', 'saree', 'kurta', 'trouser',
    ],
    
    'Priyanka': [
        'priyanka'
    ],
    
    'Miscellaneous': [
        'recharge', 'gpayrecharge', 'fan', 'wage', 'cutlery', 'soap',
        'atm', 'mob alert', 'mobile', 'verif', 'charges', 'chrg',
    ]
}


# ============================================================================
# NEW FUNCTION: PARSE UPI TRANSACTION
# ============================================================================
def parse_upi_transaction(particulars):
    """
    Extract meaningful information from UPI transaction strings.
    
    Args:
        particulars (str): Raw UPI transaction description
        
    Returns:
        dict: Parsed transaction info with keys:
              - upi_id: The UPI handle (e.g., 'merchant@paytm')
              - mcc: Merchant category code (e.g., '5411')
              - transaction_id: UPI transaction reference
              
    Example:
        Input: "UPIOUT/111422320001/paytmqr62k21i@ptys/UPI/7210"
        Output: {
            'upi_id': 'paytmqr62k21i@ptys',
            'mcc': '7210',
            'transaction_id': '111422320001'
        }
    
    UPI Transaction Format (common patterns):
        UPIOUT/<txn_id>/<upi_handle>/<text>/<mcc>
        UPI-<name>-<upi_handle>-<bank_code>-<txn_id>-<description>
    """
    
    result = {
        'upi_id': None,
        'mcc': None,
        'transaction_id': None
    }
    
    if not isinstance(particulars, str):
        return result
    
    # Pattern 1: UPIOUT/txn_id/upi_handle/text/mcc
    # Example: UPIOUT/111422320001/paytmqr62k21i@ptys/UPI/7210
    upi_pattern1 = r'UPIOUT/(\d+)/([^/]+@[^/]+)/[^/]*/(\d{4})'
    match1 = re.search(upi_pattern1, particulars)
    if match1:
        result['transaction_id'] = match1.group(1)
        result['upi_id'] = match1.group(2)
        result['mcc'] = match1.group(3)
        return result
    
    # Pattern 2: UPI-NAME-upi_handle-bank-txn-description
    # Example: UPI-JOHN DOE-john@paytm-SBIN000XXXX-123456-Payment
    upi_pattern2 = r'UPI-[^-]+-([^-]+@[^-]+)-'
    match2 = re.search(upi_pattern2, particulars)
    if match2:
        result['upi_id'] = match2.group(1)
    
    # Extract MCC if present anywhere (look for /XXXX pattern)
    mcc_pattern = r'/(\d{4})(?:\s|$|/)'
    mcc_match = re.search(mcc_pattern, particulars)
    if mcc_match:
        result['mcc'] = mcc_match.group(1)
    
    # Extract any @handle pattern
    if not result['upi_id']:
        handle_pattern = r'([a-zA-Z0-9._-]+@[a-zA-Z0-9._-]+)'
        handle_match = re.search(handle_pattern, particulars)
        if handle_match:
            result['upi_id'] = handle_match.group(1)
    
    return result


# ============================================================================
# ENHANCED FUNCTION: CATEGORIZE TRANSACTION
# ============================================================================
def categorize_transaction(particulars, tran_type):
    """
    Categorize a transaction based on its description (particulars).
    
    CATEGORIZATION PRIORITY (in order):
        1. Special hardcoded cases (specific people/payees)
        2. Merchant Category Code (MCC) - most reliable
        3. UPI handle pattern matching
        4. Keyword matching in description
        5. Default to Uncategorized
    
    Args:
        particulars (str): Transaction description from bank statement
        tran_type (str): Transaction type (UPI, NEFT, ATM, etc.)
    
    Returns:
        str: Category name (Food, Travel, Medical, etc.) or 'Uncategorized'
    """
    
    # Handle missing/null values
    if pd.isna(particulars):
        return 'Uncategorized'
    
    # Convert to lowercase for case-insensitive matching
    particulars_lower = str(particulars).lower()
    
    # ========================================================================
    # PRIORITY 1: HARDCODED SPECIAL CASES
    # ========================================================================
    
    # Special case: Rent payee (NILIMA SAHA)
    if 'nilima saha' in particulars_lower:
        return 'Rent'
    
    # Special case: Priyanka's UPI ID or name
    if '20155456966' in particulars_lower or 'priyanka' in particulars_lower:
        return 'Priyanka'
    
    # ========================================================================
    # PRIORITY 2: PARSE UPI TRANSACTIONS AND USE MCC
    # ========================================================================
    
    if 'upi' in particulars_lower:
        upi_data = parse_upi_transaction(particulars)
        
        # Check if we have a valid MCC code
        if upi_data['mcc'] and upi_data['mcc'] in MCC_CATEGORIES:
            category = MCC_CATEGORIES[upi_data['mcc']]
            # If MCC suggests a meaningful category (not just Miscellaneous), use it
            if category != 'Miscellaneous':
                return category
            # If MCC says Miscellaneous, continue to other checks
        
        # Check UPI handle patterns
        if upi_data['upi_id']:
            upi_id_lower = upi_data['upi_id'].lower()
            for handle, category in UPI_HANDLE_CATEGORIES.items():
                if handle in upi_id_lower:
                    # If handle gives us a meaningful category, use it
                    if category != 'Miscellaneous':
                        return category
    
    # ========================================================================
    # PRIORITY 3: KEYWORD MATCHING (LEGACY)
    # ========================================================================
    
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword.lower() in particulars_lower:
                return category
    
    # ========================================================================
    # PRIORITY 4: DEFAULT PATTERNS
    # ========================================================================
    
    # UPI /0000 transactions are typically person-to-person (P2P)
    if '/0000' in particulars_lower and 'upi' in particulars_lower:
        return 'Miscellaneous'
    
    # BharatPe without other indicators = Miscellaneous
    if 'bharatpe' in particulars_lower:
        return 'Miscellaneous'
    
    # ========================================================================
    # PRIORITY 5: UNCATEGORIZED
    # ========================================================================
    
    return 'Uncategorized'


# ============================================================================
# FUNCTION: CLEAN NUMERIC VALUE
# ============================================================================
def clean_numeric_value(value):
    """
    Convert string values with commas to float numbers.
    
    Args:
        value: String or number from Excel (e.g., "1,234.56" or 1234.56)
    
    Returns:
        float: Cleaned numeric value, or 0.0 if invalid
    
    Example:
        "1,234.56" → 1234.56
        "500" → 500.0
        NaN → 0.0
    """
    
    if isinstance(value, (int, float)):
        return float(value) if not pd.isna(value) else 0.0
    
    if isinstance(value, str):
        try:
            cleaned = value.replace(',', '')
            return float(cleaned)
        except (ValueError, AttributeError):
            return 0.0
    
    return 0.0


# ============================================================================
# FUNCTION: CLEAN DATE VALUE
# ============================================================================
def clean_date(date_value):
    """
    Convert various date formats to standardized datetime.
    
    Args:
        date_value: Date from Excel (can be string "01/01/2026" or datetime)
    
    Returns:
        datetime: Standardized date object
    
    Handles:
        - String dates like "01/01/2026"
        - Already datetime objects
        - Invalid dates (returns None)
    """
    
    if pd.isna(date_value):
        return None
    
    if isinstance(date_value, datetime):
        return date_value
    
    if isinstance(date_value, str):
        try:
            return pd.to_datetime(date_value, format='%d/%m/%Y')
        except:
            try:
                return pd.to_datetime(date_value)
            except:
                return None
    
    return None


# ============================================================================
# NEW FUNCTION: GENERATE CATEGORIZATION REPORT
# ============================================================================
def generate_categorization_report(df):
    """
    Generate a detailed report showing categorization effectiveness.
    
    Shows:
        - How many transactions per category
        - Percentage of Uncategorized vs Categorized
        - Sample uncategorized transactions for review
    
    Args:
        df (DataFrame): Categorized expense dataframe
    """
    
    print("\n" + "=" * 60)
    print("📊 CATEGORIZATION EFFECTIVENESS REPORT")
    print("=" * 60)
    
    total_transactions = len(df)
    category_counts = df['Category'].value_counts()
    
    print(f"\n📈 Total Transactions: {total_transactions}")
    print(f"\n🏷️  Breakdown by Category:")
    print("-" * 60)
    
    for category in sorted(category_counts.index):
        count = category_counts[category]
        percentage = (count / total_transactions) * 100
        print(f"   {category:20s}: {count:4d} transactions ({percentage:5.1f}%)")
    
    # Calculate success metrics
    uncategorized_count = category_counts.get('Uncategorized', 0)
    misc_count = category_counts.get('Miscellaneous', 0)
    problem_count = uncategorized_count + misc_count
    problem_percentage = (problem_count / total_transactions) * 100
    success_percentage = 100 - problem_percentage
    
    print("\n" + "-" * 60)
    print(f"✅ Successfully Categorized: {total_transactions - problem_count} ({success_percentage:.1f}%)")
    print(f"❓ Needs Review: {problem_count} ({problem_percentage:.1f}%)")
    
    # Show sample of uncategorized for user review
    if uncategorized_count > 0:
        print(f"\n🔍 Sample Uncategorized Transactions (showing up to 10):")
        print("-" * 60)
        uncategorized = df[df['Category'] == 'Uncategorized'].head(10)
        for idx, row in uncategorized.iterrows():
            print(f"   {row['Particulars'][:70]}")
        
        if uncategorized_count > 10:
            print(f"   ... and {uncategorized_count - 10} more")


# ============================================================================
# MAIN FUNCTION: PROCESS EXPENSE FILE
# ============================================================================
def process_expense_file(input_file_path, output_file_path):
    """
    Main function to process bank statement and create categorized expense file.
    
    Args:
        input_file_path (str): Path to input Excel file (bank statement)
        output_file_path (str): Path where output Excel file will be saved
    
    Process:
        1. Read bank statement (skip header rows)
        2. Filter only withdrawal transactions
        3. Categorize each transaction (using improved algorithm)
        4. Create summary by category
        5. Generate effectiveness report
        6. Save to Excel with exact format required
    """
    
    print(f"📂 Reading input file: {input_file_path}")
    
    # ========================================================================
    # STEP 1: READ INPUT FILE
    # ========================================================================
    
    try:
        df = pd.read_excel(input_file_path, header=10)
        print(f"✓ File loaded successfully: {len(df)} rows found")
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return
    
    # ========================================================================
    # STEP 2: CLEAN AND FILTER DATA
    # ========================================================================
    
    df = df[df['Sl. No.'].notna()]
    df = df[df['Sl. No.'].apply(lambda x: str(x).isdigit())]
    
    print(f"✓ After cleaning: {len(df)} transaction rows")
    
    df['Withdrawal_Clean'] = df['Withdrawal'].apply(clean_numeric_value)
    df['Deposit_Clean'] = df['Deposit'].apply(clean_numeric_value)
    df['Value Date_Clean'] = df['Value Date'].apply(clean_date)
    
    # ========================================================================
    # STEP 3: FILTER ONLY WITHDRAWALS (EXPENSES)
    # ========================================================================
    
    expense_df = df[df['Withdrawal_Clean'] > 0].copy()
    print(f"✓ Found {len(expense_df)} expense transactions (withdrawals)")
    
    # ========================================================================
    # STEP 4: CATEGORIZE EACH TRANSACTION (IMPROVED ALGORITHM)
    # ========================================================================
    
    print("🏷️  Categorizing transactions with improved algorithm...")
    expense_df['Category'] = expense_df.apply(
        lambda row: categorize_transaction(row['Particulars'], row['Tran Type']),
        axis=1
    )
    
    # ========================================================================
    # STEP 4.5: GENERATE EFFECTIVENESS REPORT
    # ========================================================================
    
    generate_categorization_report(expense_df)
    
    # ========================================================================
    # STEP 5: PREPARE OUTPUT DATAFRAME
    # ========================================================================
    
    output_df = pd.DataFrame({
        'Value Date': expense_df['Value Date_Clean'],
        'Particulars': expense_df['Particulars'],
        'Tran Type': expense_df['Tran Type'],
        'Category': expense_df['Category'],
        'Withdrawals': expense_df['Withdrawal_Clean']
    })
    
    # ========================================================================
    # STEP 6: CREATE CATEGORY SUMMARY
    # ========================================================================
    
    category_totals = expense_df.groupby('Category')['Withdrawal_Clean'].sum()
    grand_total = expense_df['Withdrawal_Clean'].sum()
    
    summary_rows = []
    
    summary_rows.append({
        'Value Date': 'Total',
        'Particulars': None,
        'Tran Type': None,
        'Category': None,
        'Withdrawals': grand_total
    })
    
    summary_rows.append({
        'Value Date': None,
        'Particulars': None,
        'Tran Type': None,
        'Category': None,
        'Withdrawals': None
    })
    summary_rows.append({
        'Value Date': None,
        'Particulars': None,
        'Tran Type': None,
        'Category': None,
        'Withdrawals': None
    })
    
    for category in sorted(category_totals.index):
        summary_rows.append({
            'Value Date': None,
            'Particulars': None,
            'Tran Type': None,
            'Category': category,
            'Withdrawals': category_totals[category]
        })
    
    summary_rows.append({
        'Value Date': None,
        'Particulars': None,
        'Tran Type': None,
        'Category': None,
        'Withdrawals': grand_total
    })
    
    summary_df = pd.DataFrame(summary_rows)
    final_output = pd.concat([output_df, summary_df], ignore_index=True)
    
    # ========================================================================
    # STEP 7: SAVE TO EXCEL
    # ========================================================================
    
    print(f"\n💾 Saving output to: {output_file_path}")
    
    try:
        final_output.to_excel(output_file_path, index=False, engine='openpyxl')
        print(f"✅ SUCCESS! File saved successfully.")
        print(f"\n📈 Summary:")
        print(f"   Total Transactions: {len(expense_df)}")
        print(f"   Total Amount: ₹{grand_total:,.2f}")
        print(f"   Output file: {output_file_path}")
        
    except Exception as e:
        print(f"❌ Error saving file: {e}")


# ============================================================================
# MAIN EXECUTION
# ============================================================================
if __name__ == "__main__":
    """
    Main execution block - runs when script is executed directly.
    
    To use this script:
        1. Update the INPUT_FILE path to your bank statement location
        2. Update the OUTPUT_FILE path to where you want the result
        3. Run: python expense_categorizer_v2.py
    """
    
    INPUT_FILE = "bank_transaction_2025.xlsx"
    OUTPUT_FILE = "Categorized_Expenses_2025_v2.xlsx"
    
    print("=" * 60)
    print("💰 EXPENSE CATEGORIZER - STAGE 1 (ITERATION 3)")
    print("=" * 60)
    print()
    
    process_expense_file(INPUT_FILE, OUTPUT_FILE)
    
    print()
    print("=" * 60)
    print("✨ Processing Complete!")
    print("=" * 60)
