from app.models.auth import Permission, Role, RolePermission, User, UserProjectAccess  # noqa: F401
from app.models.master import (  # noqa: F401
    Customer,
    Department,
    Location,
    Product,
    Project,
    ProjectProduct,
    ProjectSite,
    Resource,
    StatusConfig,
)
from app.models.platform import AuditLog, CustomFieldDefinition, CustomFieldValue  # noqa: F401
from app.models.imports import (  # noqa: F401
    ColumnMapping,
    DetectedColumn,
    ImportBatch,
    ImportRowReference,
    MappingTemplate,
    UploadedSheet,
    ValidationIssue,
)
from app.models.canonical import (  # noqa: F401
    ApprovalGate,
    BrdRequirement,
    DateRevision,
    DeliveryItem,
    DiscussionItem,
    HelpdeskItem,
    RequirementLink,
    ScopeDecision,
    DependencyItem,
    GapSpecification,
    ProjectPhase,
    TrackerEvent,
    WorkItem,
    WorkItemDependency,
)
from app.models.workspace import (  # noqa: F401,E402
    ActionItem, Attachment, Comment, CoverageActivity, DashboardLayout, DashboardPref, IntegrationItem, ReportItem, UatDefect, UatScenario, WeekPlanItem,
)
import app.db.lifecycle_filter  # noqa: F401,E402  (registers the archive/trash filter)
