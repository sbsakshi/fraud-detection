from datetime import date

SEED = 42

# Reference "today" for the synthetic dataset, kept fixed so runs are reproducible.
END_DATE = date(2026, 9, 14)
# Fraud scenarios are injected into the last DATE_RANGE_DAYS (START_DATE ..
# END_DATE). Base traffic starts BURN_IN_DAYS earlier, so by START_DATE every
# account already has realistic history -- otherwise every account "appears"
# with zero history on day 1, and "receiver has no history" stops meaning
# "receiver is new" (ml/train.py drops the burn-in rows before training).
DATE_RANGE_DAYS = 60
START_DATE = END_DATE.fromordinal(END_DATE.toordinal() - DATE_RANGE_DAYS)
BURN_IN_DAYS = 30
HISTORY_START = START_DATE.fromordinal(START_DATE.toordinal() - BURN_IN_DAYS)

NUM_ACCOUNTS = 6000
# Same per-day density as the original 45k-over-60-days, over 90 days.
NUM_BASE_TRANSACTIONS = 67500
# Fraction of normal accounts opened *during* the data window rather than
# before it. Without these, "brand-new account" is a perfect fraud label,
# since every scenario used to mint fresh accounts and nothing else did.
NEW_ACCOUNT_RATE = 0.06

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
# Fraction of fraud-role accounts that are existing, aged accounts (bought or
# recruited) rather than freshly opened ones -- real mule herders recruit
# established account holders precisely because new accounts draw scrutiny.
SCAM_AGED_RECIPIENT_RATE = 0.3
MULE_RECRUITED_COLLECTOR_RATE = 0.5
LAYERING_AGED_HOP_RATE = 0.3
ACCOUNT_TAKEOVER_AGED_RECEIVER_RATE = 0.5
# Takeover drains skew toward the small hours but can happen at any time.
ACCOUNT_TAKEOVER_NIGHT_RATE = 0.5

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

# Many short-lived operators rather than a handful of permanent ones: with
# only 5, every test-set operator had already been seen in training and the
# model scored "gambling" by memorizing those 5 receivers.
NUM_GAMBLING_OPERATORS = 20
GAMBLING_ACTIVE_DAYS_RANGE = (7, 20)
GAMBLING_BETTORS_RANGE = (10, 25)
GAMBLING_BETS_RANGE = (3, 10)
GAMBLING_LATE_NIGHT_RATE = 0.7

# Legitimate look-alikes (unlabelled, tagged via `scenario`) so the model has
# to learn more than "big amount" / "fan-in" / "new device":
# - large_new_payee: a one-off large payment to someone never paid before
#   (rent deposit, a used car), sometimes from a new device.
# - group_collection: one person collects from many friends in a few hours
#   (trip, gift pool) and sometimes pays a merchant onward.
NUM_LARGE_NEW_PAYEE = 450
LARGE_NEW_PAYEE_NEW_DEVICE_RATE = 0.25
NUM_GROUP_COLLECTIONS = 90
GROUP_COLLECTION_SIZE_RANGE = (8, 20)

OUTPUT_DIR = "data"
