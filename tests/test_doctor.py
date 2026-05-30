import json
import subprocess
import sys

import aiosqlite
import pytest

import bot
from bot import bootstrap_db


def run_doctor(*args):
    result=subprocess.run([sys.executable,'doctor.py',*args],cwd='.',text=True,capture_output=True,timeout=20)
    assert result.returncode==0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.asyncio
async def test_doctor_memory_sql_tools_and_config(tmp_path):
    db_path=tmp_path/'bot.sqlite'
    async with aiosqlite.connect(db_path) as db:
        await bootstrap_db(db)
    config_path=tmp_path/'config.toml'
    config_path.write_text('[panel]\nauth_token = "super-secret"\n\n[bot]\nnews_enabled = true\n',encoding='utf-8')

    paths=run_doctor('--db',str(db_path),'--config',str(config_path),'paths')
    assert paths['db_path']==str(db_path)
    status=run_doctor('--db',str(db_path),'db','status')
    assert status['db_schema_tag']==bot.DB_SCHEMA_TAG and status['state']=='current'
    config=run_doctor('--db',str(db_path),'--config',str(config_path),'config','show')
    assert config['panel']['auth_token']=='***'

    added=run_doctor('--db',str(db_path),'memory','add','123456789012345678','doctor note','--array-tags','debug')
    assert added['ok'] is True and added['backup']
    listed=run_doctor('--db',str(db_path),'memory','list','--str-discord-id','123456789012345678','--query','doctor')
    assert listed[0]['str_annotations']=='doctor note'
    dumped=run_doctor('--db',str(db_path),'dump','memories')
    assert dumped[0]['int_memory_id']==added['int_memory_id']
    updated=run_doctor('--db',str(db_path),'memory','update',str(added['int_memory_id']),'doctor updated')
    assert updated['int_superseded_memory_id']==added['int_memory_id']
    deleted=run_doctor('--db',str(db_path),'memory','delete',str(updated['int_memory_id']))
    assert added['int_memory_id'] in deleted['deleted'] and updated['int_memory_id'] in deleted['deleted']

    tables=run_doctor('--db',str(db_path),'tables')
    assert any(row['name']=='memories' for row in tables)
    query=run_doctor('--db',str(db_path),'sql','SELECT COUNT(*) AS count FROM memories')
    assert query[0]['count']==0
    tools=run_doctor('--db',str(db_path),'tools','list')
    assert any(row['name']=='bash' for row in tools)
    changed=run_doctor('--db',str(db_path),'tools','disable','bash')
    assert changed['rowcount']==1
    async with aiosqlite.connect(db_path) as db:
        await db.execute("UPDATE schema_meta SET value='0.0.1-local' WHERE key='schema_tag'")
        await db.commit()
    upgraded=run_doctor('--db',str(db_path),'db','upgrade','--yes')
    assert upgraded['ok'] is True and upgraded['schema_tag']==bot.DB_SCHEMA_TAG and upgraded['backup']

    set_result=run_doctor('--db',str(db_path),'--config',str(config_path),'config','set','bot.news_enabled','false','--yes')
    assert set_result['ok'] is True and set_result['value'] is False
    assert 'news_enabled = false' in config_path.read_text(encoding='utf-8')
