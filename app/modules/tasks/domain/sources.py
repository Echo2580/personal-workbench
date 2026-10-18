"""Source and SourceMetadata models with the seven-key projection."""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field, field_validator, model_validator

from app.modules.tasks.domain.primitives import (
    StrictModel,
    validate_optional_date,
    validate_optional_uuid,
    validate_sha256,
    validate_timestamp,
    validate_uuid,
)


Kind = Literal["text", "image", "manual"]
_TEXT_MIME: Final = "text/plain; charset=utf-8"
_IMAGE_MIMES: Final = ("image/png", "image/jpeg")
_IMAGE_EXTS: Final = {"image/png": "png", "image/jpeg": "jpg"}


class SourceMetadata(StrictModel):
    id: str
    kind: Kind
    mime_type: str = Field(alias="mimeType")
    file_name: str | None = Field(alias="fileName")
    message_date: str | None = Field(alias="messageDate")
    imported_at: str = Field(alias="importedAt")
    content_sha256: str = Field(alias="contentSha256")

    @field_validator("id")
    @classmethod
    def _id_must_be_uuid(cls, value: str) -> str:
        return validate_uuid(value, "id")

    @field_validator("content_sha256")
    @classmethod
    def _sha256_must_match(cls, value: str) -> str:
        return validate_sha256(value, "contentSha256")

    @field_validator("imported_at")
    @classmethod
    def _imported_at_must_be_stamp(cls, value: str) -> str:
        return validate_timestamp(value, "importedAt")

    @field_validator("message_date")
    @classmethod
    def _message_date_must_be_iso(cls, value: str | None) -> str | None:
        return validate_optional_date(value, "messageDate")

    @model_validator(mode="after")
    def _validate_kind_mime_filename(self) -> "SourceMetadata":
        if self.kind in ("text", "manual"):
            if self.mime_type != _TEXT_MIME:
                raise ValueError("text/manual source must declare text/plain; charset=utf-8")
            if self.file_name is not None:
                raise ValueError("text/manual source must have null fileName")
        else:
            if self.mime_type not in _IMAGE_MIMES:
                raise ValueError("image source must declare image/png or image/jpeg")
            if self.file_name is not None and (
                "/" in self.file_name or "\\" in self.file_name
            ):
                raise ValueError("fileName must not contain path separators")
        return self


class Source(SourceMetadata):
    original_text: str | None = Field(alias="originalText")
    relative_path: str | None = Field(alias="relativePath")

    @field_validator("original_text")
    @classmethod
    def _original_text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("originalText cannot be blank")
        return value

    @model_validator(mode="after")
    def _validate_source_kind_path(self) -> "Source":
        if self.kind in ("text", "manual"):
            if self.original_text is None:
                raise ValueError("text/manual source must preserve non-blank originalText")
            if self.relative_path is not None:
                raise ValueError("text/manual source must have null relativePath")
            return self

        # image
        if self.original_text is not None:
            raise ValueError("image source must have null originalText")
        expected = f"data/sources/{self.id}.{_IMAGE_EXTS[self.mime_type]}"
        if self.relative_path != expected:
            raise ValueError(
                "image source relativePath must be data/sources/<id>."
                + _IMAGE_EXTS[self.mime_type]
            )
        return self


def to_source_metadata(source: Source) -> SourceMetadata:
    """Return a new SourceMetadata projected from the seven external fields."""
    payload = {
        "id": source.id,
        "kind": source.kind,
        "mimeType": source.mime_type,
        "fileName": source.file_name,
        "messageDate": source.message_date,
        "importedAt": source.imported_at,
        "contentSha256": source.content_sha256,
    }
    return SourceMetadata.model_validate(payload)
