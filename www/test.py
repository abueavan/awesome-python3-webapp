import asyncio
import ORM
import sys
from models import User, Blog, Comment


async def test():
    await ORM.create_pool(loop,user='www-data', password='www-data', db='awesome')

    u = User(name='Test', email='test@example.com', passwd='1234567890', image='about:blank')

    await u.save()

    await ORM.destory_pool()

loop = asyncio.get_event_loop()
loop.run_until_complete(test())
loop.close()
if loop.is_closed():
	sys.exit(0)