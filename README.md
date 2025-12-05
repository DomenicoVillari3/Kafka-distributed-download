Perfetto! Ecco il README completo basato sui tuoi file definitivi:

# Kafka Satellite Data Pipeline

A distributed processing system for generating crop classification datasets from Sentinel-2 satellite imagery using Apache Kafka/Redpanda for task distribution across multiple worker nodes .

## Overview

This project implements a scalable pipeline for downloading and processing satellite imagery based on agricultural field polygons stored in GeoPackage format. The system uses Kafka/Redpanda to distribute workload across multiple worker machines, enabling parallel processing of large geographic areas .

### Key Features

- **Distributed Processing**: Kafka-based task queue for parallel execution across multiple workers
- **Sentinel-2 Integration**: Automated download from AWS Earth Search STAC API
- **Geospatial Processing**: Polygon-based chip extraction with mask generation
- **Fault Tolerance**: Automatic task rebalancing if workers fail
- **Real-time Monitoring**: Progress tracking through dedicated monitor component
- **Scalable**: Add/remove workers dynamically without interrupting processing
- **NFS Storage**: Shared filesystem for coordinated data access across nodes

---


## Quick Start

### Prerequisites

- **Master Node**: Ubuntu/Debian Linux with Docker
- **Worker Nodes**: Ubuntu/Debian Linux
- **Network**: All machines on same subnet (e.g., 192.168.128.0/24)
- **Python**: 3.8+ on all machines
- **Storage**: NFS-shared directory for GPKG and output

### Installation

#### 1. Master Node Setup

```
# Clone repository
git clone https://github.com/yourusername/kafka-satellite-pipeline.git
cd kafka-satellite-pipeline

# Install dependencies
pip install -r requirements.txt

# Setup NFS server and shared directory
chmod +x setup_master_nfs.sh
./setup_master_nfs.sh

# Copy GPKG to shared directory
cp your_data.gpkg /export/mimmo/es_2023_all.gpkg

# Update docker-compose.yml with your Master IP
nano docker-compose.yml
# Change: --advertise-kafka-addr PLAINTEXT://<YOUR_MASTER_IP>:9092

# Start Redpanda
docker-compose up -d

# Verify Redpanda is running
docker logs redpanda
```

#### 2. Worker Node Setup

```
# On each worker machine
git clone https://github.com/yourusername/kafka-satellite-pipeline.git
cd kafka-satellite-pipeline

# Install dependencies
pip install kafka-python geopandas stackstac pystac-client rasterio geocube pyogrio

# Mount NFS share
chmod +x mount_worker_nfs.sh
nano mount_worker_nfs.sh  # Update MASTER_IP if needed
./mount_worker_nfs.sh

# Verify mount
ls -la /mnt/mimmo/
```


## 🔧 Configuration

### Network Configuration

**Master IP**: `192.168.128.236` (default, change in all files if different)

Files to update if using different IP :
- `docker-compose.yml`: Line with `--advertise-kafka-addr`
- `setup_master_nfs.sh`: SUBNET variable
- `mount_worker_nfs.sh`: MASTER_IP variable
- `worker.py`: `bootstrap_servers` parameter

### Worker Configuration

Edit `worker.py` for processing parameters [:

```
self.chip_size = 256              # Output chip dimensions (pixels)
self.max_chips_per_cell = 5       # Maximum chips per geographic cell
self.gpkg_path = "/mnt/mimmo/es_2023_all.gpkg"  # Input GPKG path
self.output_dir = "/mnt/mimmo"    # Output directory
```

##  Usage Workflow

### Initial Setup (One-time)

```
# === On Master ===
# Start Redpanda
docker-compose up -d

# Create Kafka topics with 10 partitions
sudo docker exec -it redpanda rpk topic create satellite-tasks --partitions 10

# Verify topics
sudo docker exec -it redpanda rpk topic list
```

### Running the Pipeline

```
# === Step 1: Start Workers (on each worker machine) ===
python3 worker.py 1  # Worker 1
python3 worker.py 2  # Worker 2
python3 worker.py N  # Worker N

# Workers will show: "Worker N started, waiting for tasks..."

# === Step 2: Start Monitor (optional, on Master) ===
python3 monitor.py

# === Step 3: Launch Processing (on Master) ===
python3 master.py

# Master will:
# - Read GPKG
# - Generate tasks for cells with polygons
# - Publish N tasks to Kafka

# Workers will immediately start processing in parallel
```

### Monitoring Progress

```
# View consumer group status
sudo docker exec -it redpanda rpk group describe satellite-workers -v

# Expected output:
# GROUP           satellite-workers
# COORDINATOR     0
# STATE           Stable
# MEMBERS         N
# Shows assigned partitions and lag for each worker

# View topic messages
sudo docker exec -it redpanda rpk topic consume satellite-results --num 10
```

### Resetting the Pipeline

```
# Delete all tasks (if you need to restart)
sudo docker exec -it redpanda rpk topic delete satellite-tasks

# Recreate topic
sudo docker exec -it redpanda rpk topic create satellite-tasks --partitions 10
```
### Increase Partitions

More partitions = more parallel workers supported :

```
# Delete and recreate topic with more partitions
sudo docker exec -it redpanda rpk topic delete satellite-tasks
sudo docker exec -it redpanda rpk topic create satellite-tasks --partitions 20
```

---

## Data Processing Workflow

1. **Master** reads GeoPackage and generates geographic grid (e.g., 10×10 = 100 cells) 
2. **Master** filters cells with at least 5 polygons
3. **Master** publishes task JSON for each valid cell to Kafka topic `satellite-tasks`
4. **Kafka** distributes tasks across available workers using consumer group load balancing
5. For each task, **Worker** :
   - Reads polygons from GeoPackage for the cell bbox
   - Downloads Sentinel-2 imagery (2023-05-15 to 2023-06-30, cloud cover <10%)
   - Reprojects polygons to match imagery CRS (EPSG:32630)
   - Generates rasterized masks using GeoCube
   - Extracts 256×256 chips centered on field centroids
   - Saves chips and masks to shared NFS storage
   - Publishes result to `satellite-results` topic
1. **Monitor** tracks progress and aggregates statistics 


## Output Format

Generated dataset structure [file:37]:

```
/mnt/mimmo/
├── es_2023_all.gpkg           # Input (from Master)
├── images/
│   ├── worker1_task0_chip0.tif   # 10-band Sentinel-2 (uint16)
│   ├── worker1_task0_chip1.tif
│   ├── worker2_task5_chip0.tif
│   └── ...
└── masks/
    ├── worker1_task0_chip0.tif   # Single-band labels (uint8)
    ├── worker1_task0_chip1.tif
    ├── worker2_task5_chip0.tif
    └── ...
```

---

## Crop Classification Classes

The system maps EuroCrops agricultural types to 8 classes :

| Class ID | Crop Types |
|----------|------------|
| 1 | Olive plantations |
| 2 | Vineyards, wine grapes |
| 3 | Citrus, temperate/subtropical fruits |
| 4 | Almonds, orchards, forests |
| 5 | Wheat (durum/soft), barley, oats, triticale |
| 6 | Legumes (beans, chickpeas, peas, lentils) |
| 7 | Vegetables (tomato, melon, potato) |
| 8 | Fallow land, bare arable land |

### Image Bands (10 channels, 256×256 pixels, uint16)
1. Blue (B2) - 490 nm
2. Green (B3) - 560 nm
3. Red (B4) - 665 nm
4. NIR (B8) - 842 nm
5. Red Edge 1 (B5) - 705 nm
6. Red Edge 2 (B6) - 740 nm
7. Red Edge 3 (B7) - 783 nm
8. NIR narrow (B8A) - 865 nm
9. SWIR 1 (B11) - 1610 nm
10. SWIR 2 (B12) - 2190 nm

**Spatial Resolution**: 10 meters/pixel  
**CRS**: EPSG:32630 (WGS 84 / UTM zone 30N)




---
