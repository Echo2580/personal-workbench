"""构造样本测试 T04-B 来源实体与元数据投影。

所有数据均为实体测试的构造样本，不代表真实提取或保存结果。
"""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.modules.tasks.domain import Source, SourceMetadata, to_source_metadata


SOURCE_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "99999999-9999-4999-8999-999999999999"
STAMP = "2026-10-20T08:00:00+08:00"

TEXT_SOURCE = {
    "id": SOURCE_ID,
    "kind": "text",
    "originalText": "  请交报告\n",
    "relativePath": None,
    "mimeType": "text/plain; charset=utf-8",
    "fileName": None,
    "messageDate": None,
    "importedAt": STAMP,
    "contentSha256": "a" * 64,
}


def _image_source(**overrides):
    payload = {
        "id": SOURCE_ID,
        "kind": "image",
        "originalText": None,
        "relativePath": f"data/sources/{SOURCE_ID}.png",
        "mimeType": "image/png",
        "fileName": None,
        "messageDate": None,
        "importedAt": STAMP,
        "contentSha256": "a" * 64,
    }
    payload.update(overrides)
    return payload


def test_source_and_metadata_fields():
    source = Source.model_validate(TEXT_SOURCE)

    assert source.original_text == "  请交报告\n"
    assert source.message_date is None
    assert source.model_dump(mode="json", by_alias=True) == TEXT_SOURCE

    # text 的 MIME/fileName/relativePath 不一致均失败。
    for payload in (
        {**TEXT_SOURCE, "mimeType": "image/png"},
        {**TEXT_SOURCE, "fileName": "通知.png"},
        {**TEXT_SOURCE, "relativePath": f"data/sources/{SOURCE_ID}.png"},
    ):
        with pytest.raises(ValidationError):
            Source.model_validate(payload)

    # image 的 originalText 不为 null 失败。
    with pytest.raises(ValidationError):
        Source.model_validate(_image_source(originalText="文字"))


def test_source_kind_and_path():
    assert Source.model_validate(_image_source()).relative_path == (
        f"data/sources/{SOURCE_ID}.png"
    )
    # JPEG 与 MIME 对应。
    assert Source.model_validate(
        _image_source(
            relativePath=f"data/sources/{SOURCE_ID}.jpg",
            mimeType="image/jpeg",
        )
    ).relative_path == f"data/sources/{SOURCE_ID}.jpg"
    # fileName=null 通过。
    assert Source.model_validate(_image_source()).file_name is None
    # 展示文件名不含分隔符时可保留。
    assert (
        Source.model_validate(_image_source(fileName="通知.png")).file_name
        == "通知.png"
    )

    invalid_paths = [
        f"D:\\data\\sources\\{SOURCE_ID}.png",
        f"/data/sources/{SOURCE_ID}.png",
        f"data/sources/../{SOURCE_ID}.png",
        f"data\\sources\\{SOURCE_ID}.png",
        f"data/sources/{OTHER_ID}.png",
        f"data/sources/{SOURCE_ID}.txt",
        "data/sources/notice.png",
    ]
    for path in invalid_paths:
        with pytest.raises(ValidationError):
            Source.model_validate(_image_source(relativePath=path))

    # MIME/扩展不匹配失败。
    with pytest.raises(ValidationError):
        Source.model_validate(
            _image_source(relativePath=f"data/sources/{SOURCE_ID}.jpg")
        )
    with pytest.raises(ValidationError):
        Source.model_validate(
            _image_source(
                relativePath=f"data/sources/{SOURCE_ID}.png",
                mimeType="image/jpeg",
            )
        )
    # 展示文件名含路径分隔符失败。
    for name in ("../通知.png", "a/b.png", "a\\b.png"):
        with pytest.raises(ValidationError):
            Source.model_validate(_image_source(fileName=name))


def test_source_scalar_formats():
    # 合法闰日及 null 消息日期通过；非法日期/空串失败，且不填导入日期。
    assert Source.model_validate(
        {**TEXT_SOURCE, "messageDate": "2024-02-29"}
    ).message_date == "2024-02-29"
    for bad_date in ("2026-2-3", "2026-02-30", "not-a-date", ""):
        with pytest.raises(ValidationError):
            Source.model_validate({**TEXT_SOURCE, "messageDate": bad_date})
    assert Source.model_validate(TEXT_SOURCE).message_date is None

    # UUID 规范性。
    for bad_id in (
        "ABCDEFAB-ABCD-4ABC-8ABC-ABCDEFABCDEF",
        SOURCE_ID.replace("-", ""),
        "11111111-1111-4111-8111-11111111111g",
    ):
        with pytest.raises(ValidationError):
            Source.model_validate({**TEXT_SOURCE, "id": bad_id})

    # SHA-256：64 位十六进制（大小写均可）通过；63 位或非 ASCII 失败。
    assert Source.model_validate(
        {**TEXT_SOURCE, "contentSha256": "A" * 64}
    ).content_sha256 == "A" * 64
    assert Source.model_validate(
        {**TEXT_SOURCE, "contentSha256": "0123456789abcdef" * 4}
    ).content_sha256 == "0123456789abcdef" * 4
    for bad_sha in ("a" * 63, "g" * 64, "，" * 64, "a" * 65):
        with pytest.raises(ValidationError):
            Source.model_validate({**TEXT_SOURCE, "contentSha256": bad_sha})

    # 时间戳格式。
    for bad_stamp in (
        "2026-10-20T08:00:00",
        "2026-10-20T08:00:00Z",
        "2026-10-20T08:00:00+00:00",
        "2026-10-20",
        "2026-13-20T08:00:00+08:00",
    ):
        with pytest.raises(ValidationError):
            Source.model_validate({**TEXT_SOURCE, "importedAt": bad_stamp})
    assert Source.model_validate(
        {**TEXT_SOURCE, "importedAt": "2026-10-20T08:00:00.123+08:00"}
    ).imported_at == "2026-10-20T08:00:00.123+08:00"


def test_source_metadata_projection():
    source = Source.model_validate(TEXT_SOURCE)
    source_dump = source.model_dump(mode="json", by_alias=True)

    meta = to_source_metadata(source)

    assert isinstance(meta, SourceMetadata)
    assert set(meta.model_dump(by_alias=True)) == {
        "id",
        "kind",
        "mimeType",
        "fileName",
        "messageDate",
        "importedAt",
        "contentSha256",
    }
    dumped = meta.model_dump(mode="json", by_alias=True)
    assert "originalText" not in dumped
    assert "relativePath" not in dumped
    assert dumped == {
        "id": SOURCE_ID,
        "kind": "text",
        "mimeType": "text/plain; charset=utf-8",
        "fileName": None,
        "messageDate": None,
        "importedAt": STAMP,
        "contentSha256": "a" * 64,
    }
    # 原来源未被修改。
    assert source.model_dump(mode="json", by_alias=True) == source_dump

    image = Source.model_validate(_image_source(fileName="通知.png"))
    image_meta = to_source_metadata(image)
    assert image_meta.file_name == "通知.png"
    assert "relativePath" not in image_meta.model_dump(by_alias=True)

    # SourceMetadata 拒绝多余内部键。
    for extra in ("originalText", "relativePath"):
        payload = {
            "id": SOURCE_ID,
            "kind": "text",
            "mimeType": "text/plain; charset=utf-8",
            "fileName": None,
            "messageDate": None,
            "importedAt": STAMP,
            "contentSha256": "a" * 64,
            extra: "value",
        }
        with pytest.raises(ValidationError):
            SourceMetadata.model_validate(payload)


def test_source_required_keys_and_round_trip():
    for model, payload in ((SourceMetadata, to_source_metadata(Source.model_validate(TEXT_SOURCE)).model_dump(mode="json", by_alias=True)), (Source, TEXT_SOURCE)):
        for key in payload:
            incomplete = deepcopy(payload)
            del incomplete[key]
            with pytest.raises(ValidationError):
                model.model_validate(incomplete)

        with pytest.raises(ValidationError):
            model.model_validate({**payload, "unknown": "value"})

        snake = deepcopy(payload)
        snake.pop("importedAt")
        snake["imported_at"] = STAMP
        with pytest.raises(ValidationError):
            model.model_validate(snake)

        obj = model.model_validate(payload)
        rebuilt = model.model_validate_json(obj.model_dump_json(by_alias=True))
        assert rebuilt.model_dump(mode="json", by_alias=True) == (
            obj.model_dump(mode="json", by_alias=True)
        )

    for payload in (TEXT_SOURCE, _image_source(fileName="通知.png")):
        obj = Source.model_validate(payload)
        rebuilt = Source.model_validate_json(obj.model_dump_json(by_alias=True))
        assert rebuilt.model_dump(mode="json", by_alias=True) == payload
