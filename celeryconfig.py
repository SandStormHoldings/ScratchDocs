from datetime import timedelta
from config import REDIS_BROKER as BROKER_URL

CELERYD_CONCURRENCY=1
CELERYD_MAX_TASKS_PER_CHILD=5
CELERYBEAT_SCHEDULE = {
    'feed-populate': {
        'task': 'tasks.changes_to_feed',
        'schedule': timedelta(minutes=15),
    },
}
