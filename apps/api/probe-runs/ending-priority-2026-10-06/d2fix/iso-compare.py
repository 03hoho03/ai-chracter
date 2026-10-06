"""격리 DB 의 활성 story 세트 stat_judgment 섹션·측정 방 스탯 정의를 운영 덤프(q-stat.out)와 비교한다. 읽기만 한다."""
import asyncio, hashlib, re, sys, uuid
from pathlib import Path
from sqlalchemy import select, text
from api.db.session import async_session_factory
from api.chat.prompt_builder import load_active_prompt_set
from api.db.models.chat import ChatRoom
from api.db.models.story import StatDef, StartingSetup

ROOM = uuid.UUID("6787bb78-c54d-4c65-966c-024e1dff0c74")
out = Path(sys.argv[1]).read_text(encoding="utf-8")
blocks = re.split(r"^#### ", out, flags=re.M)[1:]
prod_sec, prod_stat = {}, {}
for b in blocks:
    head, _, body = b.partition("|")
    rest = b
    if b.startswith("stat_judgment|"):
        parts = b.split("|", 6)
        slot, md5 = parts[2], parts[5]
        body = parts[6]
        body = re.sub(r"\n\(\d+ rows?\)\n.*\Z", "", body, flags=re.S)
        prod_sec[slot] = (md5, body)
    elif b.startswith("stat|"):
        parts = b.split("|", 10)
        name = parts[1]
        body = re.sub(r"\n\(\d+ rows?\)\n.*\Z", "", parts[10], flags=re.S)
        prod_stat[name] = dict(min=int(parts[3]), max=int(parts[4]), init=int(parts[5]), mcp=parts[6], dir=parts[7], desc=body)

async def main():
    async with async_session_factory() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        ps, sections = await load_active_prompt_set(db, lane="story")
        print("isolated active story set", ps.id, ps.version)
        iso = {s.slot: s.body for s in sections if s.channel == "stat_judgment"}
        for slot in sorted(set(iso) | set(prod_sec)):
            a = hashlib.md5(iso[slot].encode()).hexdigest() if slot in iso else None
            p = prod_sec.get(slot, (None, None))
            same = a == p[0] and (p[1] is None or p[1] == iso.get(slot))
            print(f"section {slot}: iso={a} prod={p[0]} {'SAME' if same else 'DIFF'}")
        room = await db.get(ChatRoom, ROOM)
        defs = (await db.scalars(select(StatDef).join(StartingSetup, StartingSetup.id == StatDef.starting_setup_id).where(StartingSetup.content_version_id == room.content_version_id, StartingSetup.entity_id == room.starting_setup_entity_id).order_by(StatDef.order))).all()
        for d in defs:
            p = prod_stat.get(d.name)
            print(d.name, "iso", d.min_value, d.max_value, d.initial_value, d.max_change_per_turn, d.change_direction,
                  "| prod", p and (p['min'], p['max'], p['init'], p['mcp'], p['dir']),
                  "| desc", "SAME" if p and p['desc'] == d.description else "DIFF")
asyncio.run(main())
