from datetime import date

SEED = 42

# Reference "today" for the synthetic dataset, kept fixed so runs are reproducible.
END_DATE = date(2026, 9, 14)
DATE_RANGE_DAYS = 60
START_DATE = END_DATE.fromordinal(END_DATE.toordinal() - DATE_RANGE_DAYS)

NUM_ACCOUNTS = 6000
NUM_BASE_TRANSACTIONS = 45000

MERCHANT_ACCOUNT_RATE = 0.15
SECOND_DEVICE_RATE = 0.10  # fraction of individual accounts with a second, occasionally-used device

# (full name, IFSC prefix, UPI handle) — synthetic, not tied to any real institution's actual codes.
BANKS = [
    ("State Bank of India", "SBIN", "oksbi"),
    ("HDFC Bank", "HDFC", "okhdfcbank"),
    ("ICICI Bank", "ICIC", "okicici"),
    ("Axis Bank", "UTIB", "okaxis"),
    ("Kotak Mahindra Bank", "KKBK", "kotak"),
    ("Punjab National Bank", "PUNB", "pnb"),
    ("Bank of Baroda", "BARB", "barodampay"),
    ("Canara Bank", "CNRB", "cnrb"),
    ("Yes Bank", "YESB", "ybl"),
    ("IDFC First Bank", "IDFB", "idfcfirst"),
]

MERCHANT_CATEGORIES = [
    "Grocery",
    "Electronics",
    "Food & Dining",
    "Fuel",
    "Pharmacy",
    "Fashion",
    "Utilities",
    "Home Services",
    "Travel",
]

# Scenario injector scale. Tuned so the six patterns combined add ~5.5-6k
# transactions on top of NUM_BASE_TRANSACTIONS, keeping the full batch at 50k+.
NUM_SCAM_RINGS = 40
SCAM_VICTIMS_RANGE = (10, 30)

NUM_MULE_RINGS = 40
MULE_FANIN_RANGE = (10, 25)
MULE_COLLECTORS_RANGE = (3, 5)
MULE_CASHOUTS_RANGE = (1, 2)

NUM_LAYERING_CHAINS = 150
LAYERING_CHAIN_LENGTH_RANGE = (4, 7)

NUM_INNOCENT_BYSTANDERS = 500

NUM_ACCOUNT_TAKEOVERS = 180
ACCOUNT_TAKEOVER_DRAIN_RANGE = (1, 3)

NUM_GAMBLING_OPERATORS = 5
GAMBLING_BETTORS_RANGE = (30, 60)
GAMBLING_BETS_RANGE = (4, 15)

OUTPUT_DIR = "data"
