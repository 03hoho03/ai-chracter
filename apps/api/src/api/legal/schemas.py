from datetime import datetime
from typing import Literal

from api.core.schema import CamelModel

LegalDocumentKind = Literal["terms", "privacy"]


class LegalDocumentPublicResponse(CamelModel):
    kind: LegalDocumentKind
    version: str
    body_markdown: str
    published_at: datetime


class LegalConsentRequest(CamelModel):
    kind: LegalDocumentKind
    version: str
