import pytest

from dirac.provider.fake import FakeProviderClient
from dirac.types import ProviderRequest


@pytest.mark.asyncio
async def test_fake_provider_records_requests() -> None:
    provider = FakeProviderClient("hello")
    response = await provider.chat(
        ProviderRequest(messages=[{"role": "user", "content": "hi"}], model="fake-model")
    )
    assert response.content == "hello"
    assert provider.requests[0].model == "fake-model"
