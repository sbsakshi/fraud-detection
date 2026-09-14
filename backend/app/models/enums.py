import enum


class AccountType(str, enum.Enum):
    INDIVIDUAL = "individual"
    MERCHANT = "merchant"


class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class InterventionLevel(str, enum.Enum):
    INFORM = "inform"
    WARN = "warn"
    VERIFY = "verify"
    HOLD = "hold"
    RESTRICT = "restrict"
    ESCALATE = "escalate"


class ReasonCodeSource(str, enum.Enum):
    RULE = "rule"
    ML = "ml"
    GRAPH = "graph"


class GraphEdgeType(str, enum.Enum):
    TRANSACTION = "transaction"
    SHARED_DEVICE = "shared_device"
    REPEATED_COUNTERPARTY = "repeated_counterparty"


class CaseStatus(str, enum.Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    ESCALATED = "escalated"
    CLOSED = "closed"


class CaseSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
