import pytest
from bot import MemoryManager

@pytest.mark.asyncio
async def test_memory_add_search_update_approve(db):
    mm=MemoryManager(db)
    mid=await mm.add('123456789012345678','likes violin','music',0.8,'bot_pending')
    rows=await mm.search('123456789012345678','violin',pending=True); assert rows and rows[0]['int_memory_id']==mid
    nid=await mm.update(mid,'likes viola','music',0.9,'operator')
    rows=await mm.search('123456789012345678','viola'); assert rows[0]['int_memory_id']==nid
    await mm.approve(mid)  # superseded rows are not returned by active search but remain auditable
    cur = await db.execute('SELECT str_created_by FROM memories WHERE int_memory_id=?', (mid,))
    assert (await cur.fetchone())[0] == 'bot'
    await mm.delete(nid)
    assert await mm.search('123456789012345678','viola')==[]
    assert await mm.search('123456789012345678','violin')==[]

@pytest.mark.asyncio
async def test_deleting_current_memory_does_not_reactivate_old_note(db):
    mm=MemoryManager(db)
    old=await mm.add('123456789012345678','old note')
    new=await mm.update(old,'new note')
    await mm.delete(new)
    assert await mm.search('123456789012345678','old')==[]
    cur=await db.execute('SELECT COUNT(*) FROM memories WHERE int_memory_id IN (?,?)',(old,new))
    assert (await cur.fetchone())[0]==0
