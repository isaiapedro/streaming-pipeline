# Medical Data Streaming Pipeline

## Overview
The Medical Data Streaming Pipeline is a Python-based system that ingests medical data from a Kafka message broker, processes it using Spark Structured Streaming, and writes the processed data to InfluxDB. The pipeline also includes a Grafana front-end for visualizing the output.

This project is designed for healthcare organizations looking to monitor vital signs in real-time. It provides a scalable and fault-tolerant solution for processing large volumes of medical data.

## Tech stack
* Python 3.x
* Kafka (for message broker)
* Spark Structured Streaming (for data processing)
* InfluxDB (for data lake and visualization)
* Grafana (for front-end visualization)

## Getting started
To get started with this project, follow these steps:

1. Install the required dependencies by running `pip install -r requirements.txt`.
2. Start the Docker containers using `docker-compose up -d`.
3. Run the producer script to generate mock data and send it to Kafka: `python producer.py`.
4. Run the Spark job to process the data and write it to InfluxDB: `spark-submit spark_processor.py`.

## Project layout
The project is organized into the following top-level folders:

* `producer`: contains the Python script for generating mock data and sending it to Kafka.
* `spark_processor`: contains the Python script for processing the data using Spark Structured Streaming.
* `docker-compose.yml`: defines the Docker containers and their dependencies.

## Testing
To run tests, you can use the following command: `pytest`. However, since this project does not include any unit tests or integration tests, running `pytest` will not provide any output.