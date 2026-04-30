from confluent_kafka import Producer
import json
import time
import random

# 1. Configure the Kafka Producer to connect to our Docker container
conf = {'bootstrap.servers': 'localhost:9092'}
producer = Producer(conf)

topic = 'medical_signals'

print("Starting to transmit vitals. Press Ctrl+C to stop.")

while True:
    # 2. Generate mock data
    data = {
        "patient_id": "P-001",
        "heart_rate": random.randint(60, 120),
        "temperature": round(random.uniform(36.0, 39.0), 1),
        "timestamp": int(time.time())
    }
    
    # 3. Serialize to JSON and encode to bytes
    json_payload = json.dumps(data).encode('utf-8')
    
    # 4. Send to Kafka
    producer.produce(topic, value=json_payload)
    producer.flush()
    
    print(f"Sent: {data}")
    time.sleep(2)