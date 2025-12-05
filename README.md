# Kafka Satellite Data Pipeline

A distributed processing system for generating crop classification datasets from Sentinel-2 satellite imagery using Apache Kafka/Redpanda for task distribution across multiple worker nodes.

## 📋 Overview

This project implements a scalable pipeline for downloading and processing satellite imagery based on agricultural field polygons stored in GeoPackage format [web:22]. The system uses Kafka/Redpanda to distribute workload across multiple worker machines, enabling parallel processing of large geographic areas.

### Key Features

- **Distributed Processing**: Kafka-based task queue for parallel execution across multiple workers [web:30]
- **Sentinel-2 Integration**: Automated download from AWS Earth Search STAC API
- **Geospatial Processing**: Polygon-based chip extraction with mask generation
- **Fault Tolerance**: Automatic task rebalancing if workers fail
- **Real-time Monitoring**: Progress tracking through dedicated monitor component
- **Scalable**: Add/remove workers dynamically without interrupting processing


## Flow 

### Master
- `sudo docker exec -it redpanda rpk topic delete satellite-tasks` to delete the published tasks by the master
- `sudo docker exec -it redpanda rpk topic create satellite-tasks --partitions 10`to create the topic with the specified name and $N$ partitions
- `python3 master.py` to execute the master which publishes $N$ tasks (e.g., 100)
- `sudo docker exec -it redpanda rpk group describe satellite-workers -v` to describe the environment with the workers and their relative tasks
