import json
from pathlib import Path

import httpx
import pytest
import respx

from ai_dashboard.sources.base import SourceError, SourceRateLimited
from ai_dashboard.sources.huggingface import HuggingFaceAdapter


MODELS_URL = "https://huggingface.co/api/models?sort=createdAt&direction=-1&limit=30"
DATASETS_URL = (
    "https://huggingface.co/api/datasets?sort=createdAt&direction=-1&limit=20"
)
SPACES_URL = "https://huggingface.co/api/spaces?sort=createdAt&direction=-1&limit=20"


@pytest.mark.asyncio
async def test_hf_fetches_all_three_kinds() -> None:
    async with httpx.AsyncClient() as client:
        adapter = HuggingFaceAdapter(http=client, options={})

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(MODELS_URL).respond(
                json=json.loads(Path("tests/fixtures/hf_models.json").read_text())
            )
            _ = mock.get(DATASETS_URL).respond(
                json=json.loads(Path("tests/fixtures/hf_datasets.json").read_text())
            )
            _ = mock.get(SPACES_URL).respond(
                json=json.loads(Path("tests/fixtures/hf_spaces.json").read_text())
            )

            items = await adapter.fetch()

    assert len(items) == 4


@pytest.mark.asyncio
async def test_hf_source_uid_prefixes() -> None:
    async with httpx.AsyncClient() as client:
        adapter = HuggingFaceAdapter(http=client, options={})

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(MODELS_URL).respond(
                json=json.loads(Path("tests/fixtures/hf_models.json").read_text())
            )
            _ = mock.get(DATASETS_URL).respond(
                json=json.loads(Path("tests/fixtures/hf_datasets.json").read_text())
            )
            _ = mock.get(SPACES_URL).respond(
                json=json.loads(Path("tests/fixtures/hf_spaces.json").read_text())
            )

            items = await adapter.fetch()

    model_items = [item for item in items if item.source_uid.startswith("model:")]
    dataset_items = [item for item in items if item.source_uid.startswith("dataset:")]
    space_items = [item for item in items if item.source_uid.startswith("space:")]

    assert len(model_items) == 2
    assert len(dataset_items) == 1
    assert len(space_items) == 1


@pytest.mark.asyncio
async def test_hf_raw_payload() -> None:
    async with httpx.AsyncClient() as client:
        adapter = HuggingFaceAdapter(http=client, options={})

        with respx.mock(assert_all_called=True) as mock:
            _ = mock.get(MODELS_URL).respond(
                json=json.loads(Path("tests/fixtures/hf_models.json").read_text())
            )
            _ = mock.get(DATASETS_URL).respond(
                json=json.loads(Path("tests/fixtures/hf_datasets.json").read_text())
            )
            _ = mock.get(SPACES_URL).respond(
                json=json.loads(Path("tests/fixtures/hf_spaces.json").read_text())
            )

            items = await adapter.fetch()

    by_uid = {item.source_uid: item for item in items}

    model_1 = by_uid["model:MetaAI/llama-4-8b-instruct"]
    model_2 = by_uid["model:anthropic-community/claude-style-embed"]
    dataset = by_uid["dataset:bigscience/aya-extended"]
    space = by_uid["space:openai/gpt-5-playground"]

    assert model_1.raw_payload["hf_kind"] == "model"
    assert model_2.raw_payload["hf_kind"] == "model"
    assert dataset.raw_payload["hf_kind"] == "dataset"
    assert space.raw_payload["hf_kind"] == "space"

    assert model_1.raw_payload["pipeline_tag"] == "text-generation"
    assert model_2.raw_payload["pipeline_tag"] == "feature-extraction"
    assert dataset.raw_payload["pipeline_tag"] is None
    assert space.raw_payload["pipeline_tag"] is None

    assert model_1.raw_payload["author"] == "MetaAI"
    assert model_2.raw_payload["author"] == "anthropic-community"
    assert dataset.raw_payload["author"] == "bigscience"
    assert space.raw_payload["author"] == "openai"

    assert model_1.raw_payload["downloads"] == 125000
    assert model_2.raw_payload["downloads"] == 8700
    assert dataset.raw_payload["downloads"] == 45000
    assert space.raw_payload["downloads"] == 0


@pytest.mark.asyncio
async def test_hf_rate_limited_raises() -> None:
    async with httpx.AsyncClient() as client:
        adapter = HuggingFaceAdapter(http=client, options={})

        with respx.mock(assert_all_called=False) as mock:
            _ = mock.get(MODELS_URL).respond(status_code=429)
            _ = mock.get(DATASETS_URL).respond(json=[])
            _ = mock.get(SPACES_URL).respond(json=[])

            assert issubclass(SourceRateLimited, SourceError)
            with pytest.raises(SourceRateLimited):
                _ = await adapter.fetch()


def test_hf_no_huggingface_hub_import() -> None:
    file_text = Path("src/ai_dashboard/sources/huggingface.py").read_text()
    assert "huggingface_hub" not in file_text
