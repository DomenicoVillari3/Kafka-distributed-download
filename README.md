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


