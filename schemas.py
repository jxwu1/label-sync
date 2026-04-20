from dataclasses import asdict, dataclass, field


@dataclass
class BarcodeWarning:
    barcode: str
    length: int
    normal: int
    corrected: bool = False
    new_barcode: str | None = None
    deleted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LocationWarning:
    location: str
    corrected: bool = False
    new_location: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Phase2Warning:
    barcode: str
    reason: str
    locations: list[str] = field(default_factory=list)
    stockpile_stores: list[str] = field(default_factory=list)
    stockpile_warehouses: list[str] = field(default_factory=list)
    scan_stores: list[str] = field(default_factory=list)
    scan_warehouses: list[str] = field(default_factory=list)
    resolved: bool = False
    resolution: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TaskSnapshot:
    running: bool = False
    log: list[str] = field(default_factory=list)
    result_zip: str | None = None
    error: bool = False
    barcode_warnings: list[BarcodeWarning] = field(default_factory=list)
    location_warnings: list[LocationWarning] = field(default_factory=list)
    waiting: bool = False
    waiting_stage: str | None = None
    new_barcodes: list[str] = field(default_factory=list)
    phase2_warnings: list[Phase2Warning] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["barcode_warnings"] = [warning.to_dict() for warning in self.barcode_warnings]
        data["location_warnings"] = [warning.to_dict() for warning in self.location_warnings]
        data["phase2_warnings"] = [warning.to_dict() for warning in self.phase2_warnings]
        return data


@dataclass
class TextMessage:
    id: int
    text: str
    sender: str
    time: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ServiceResult:
    ok: bool
    payload: dict = field(default_factory=dict)
    status_code: int = 200

    def to_response_body(self) -> dict:
        return {"ok": self.ok, **self.payload}
