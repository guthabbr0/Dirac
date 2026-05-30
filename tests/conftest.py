import os
import sys
import asyncio

import aiosqlite
import pytest
import pytest_asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pytest_plugins = ['pytest_asyncio']

@pytest.fixture(autouse=True)
def reset_runtime_control():
    import bot
    bot.runtime_control.resume()
    yield
    bot.runtime_control.resume()

@pytest_asyncio.fixture
async def db():
    async with aiosqlite.connect(':memory:') as conn:
        from bot import bootstrap_db
        await bootstrap_db(conn)
        yield conn


@pytest_asyncio.fixture
async def runtime_tg():
    async with asyncio.TaskGroup() as tg:
        yield tg


class _StubOllama:
    def __init__(self): self.calls=[]
    async def chat(self, messages, tools=None, model=None, scope_type='panel', scope_id=None, **kwargs):
        self.calls.append({'messages':messages,'tools':tools,'model':model,'scope_type':scope_type,'scope_id':scope_id,'kwargs':kwargs})
        return {'message':{'content':'stub-response'}}
