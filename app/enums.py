from enum import Enum

class ThreatEnum(Enum):
    CALM = "calm"
    DRONES = "drones"
    BALLISTICS = "ballistics"
    COMBINED = "combined"
    RED_LEVEL = "redLevel"


class StaffRole(str, Enum):
    ADMIN = "admin"
    SUPERADMIN = "superadmin"
