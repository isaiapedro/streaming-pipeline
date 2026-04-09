from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, when
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DoubleType
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

# 1. Initialize Spark Session
spark = SparkSession.builder \
    .appName("MedicalVitalsStreaming") \
    .getOrCreate()

# 2. Define the schema of our incoming JSON data
schema = StructType([
    StructField("patient_id", StringType(), True),
    StructField("heart_rate", IntegerType(), True),
    StructField("temperature", DoubleType(), True),
    StructField("timestamp", IntegerType(), True)
])

# 3. Read from Kafka (readStream)
raw_df = spark.readStream \
    .format("kafka") \
    .option("kafka.bootstrap.servers", "localhost:9092") \
    .option("subscribe", "medical_signals") \
    .option("startingOffsets", "latest") \
    .load()

# 4. Parse JSON and apply the ALARM RULE
parsed_df = raw_df.select(from_json(col("value").cast("string"), schema).alias("data")).select("data.*")

# Applying the rule: If heart_rate > 100, alarm is True
processed_df = parsed_df.withColumn(
    "alarm_triggered", 
    when(col("heart_rate") > 100, True).otherwise(False)
)

# 5. Define the function to write data to InfluxDB
def write_to_influxdb(df, epoch_id):
    # Collect the micro-batch to the driver (fine for small MVPs)
    records = df.collect()
    
    # InfluxDB connection details (matching our Docker setup!)
    url = "http://localhost:8086"
    token = "super-secret-auth-token"
    org = "hospital"
    bucket = "vitals"
    
    client = InfluxDBClient(url=url, token=token, org=org)
    write_api = client.write_api(write_options=SYNCHRONOUS)
    
    for row in records:
        # Create a time-series point
        point = Point("patient_vitals") \
            .tag("patient_id", row["patient_id"]) \
            .field("heart_rate", row["heart_rate"]) \
            .field("temperature", row["temperature"]) \
            .field("alarm", row["alarm_triggered"])
        
        write_api.write(bucket=bucket, org=org, record=point)
    
    client.close()

# 6. Start the stream (writeStream) using foreachBatch
query = processed_df.writeStream \
    .outputMode("append") \
    .foreachBatch(write_to_influxdb) \
    .start()

query.awaitTermination()