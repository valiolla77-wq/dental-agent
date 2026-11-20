from typing import Literal

from pydantic import BaseModel, Field


class PatientCreate(BaseModel):
    national_id: str = Field(min_length=1, max_length=50)
    full_name: str = Field(min_length=1, max_length=150)
    phone: str = Field(min_length=8, max_length=20)


class PatientUpdate(BaseModel):
    full_name: str
    phone: str
    # Optional for staff completion of a legacy record. ``None`` means
    # "not provided" and never clears a stored national id; the value is
    # normalized (Persian/Arabic digits) server-side.
    national_id: str | None = Field(default=None, max_length=50)


class PatientSelfRegister(BaseModel):
    """Patient-account registration, either for the holder or a dependent.

    ``relation`` is required so the server can enforce that a ``self`` record
    uses the account phone and that every account has at most one holder
    record. ``other`` records are family/dependent patients with their own
    unique phone number.
    """

    full_name: str = Field(min_length=3, max_length=150)
    phone: str = Field(min_length=8, max_length=20)
    national_id: str = Field(min_length=10, max_length=10)
    relation: Literal["self", "other"]


class PatientResponse(BaseModel):
    id: int
    national_id: str | None
    full_name: str
    phone: str
    is_account_holder: bool = False
    record_status: str
    # Linked patient-account id (NULL = no app login yet). Harmless
    # bookkeeping info that lets the staff UI show the link state and offer
    # the admin-only connect action.
    user_id: int | None = None

    model_config = {
        "from_attributes": True
    }
