# monitor.py
import json
from kafka import KafkaConsumer
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

consumer = KafkaConsumer(
    'satellite-results',
    bootstrap_servers=['localhost:9092'],
    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
    auto_offset_reset='earliest'
)

total_chips = 0
completed_tasks = 0

logger.info("Monitor started...")

for message in consumer:
    result = message.value
    completed_tasks += 1
    total_chips += result.get('chips_saved', 0)
    
    logger.info(
        f"Task {result['task_id']} ({result['status']}): "
        f"{result['chips_saved']} chips | "
        f"Total: {completed_tasks} tasks, {total_chips} chips"
    )
