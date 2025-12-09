

# Kafka Satellite Data Pipeline

A distributed processing system for generating crop classification datasets from Sentinel-2 satellite imagery using Apache Kafka/Redpanda for task distribution across multiple worker nodes.

## Overview

This project implements a scalable pipeline for downloading and processing satellite imagery based on agricultural field polygons stored in GeoPackage format. The system uses Kafka/Redpanda to distribute workload across multiple worker machines, enabling parallel processing of large geographic areas.

### Key Features

- **Distributed Processing**: Kafka-based task queue for parallel execution across multiple workers  
- **Sentinel-2 Integration**: Automated download from AWS Earth Search STAC API  
- **Geospatial Processing**: Polygon-based chip extraction with mask generation  
- **Probabilistic Sampling**: Class-wise sampling probabilities to balance the dataset  
- **Fault Tolerance**: Automatic task rebalancing if workers fail  
- **Real-time Monitoring**: Progress tracking through dedicated monitor component  
- **Scalable**: Add/remove workers dynamically without interrupting processing  
- **NFS Storage**: Shared filesystem for coordinated data access across nodes  

***

## Quick Start

### Prerequisites

- **Master Node**: Ubuntu/Debian Linux with Docker  
- **Worker Nodes**: Ubuntu/Debian Linux  
- **Network**: All machines on same subnet (e.g., 192.168.128.0/24)  
- **Python**: 3.8+ on all machines  
- **Storage**: NFS-shared directory for GPKG and output  

### Installation

#### 1. Master Node Setup

```bash
# Clone repository
git clone https://github.com/yourusername/kafka-satellite-pipeline.git
cd kafka-satellite-pipeline

# (Optional) Create virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup NFS server and shared directory
chmod +x setup_master_nfs.sh
./setup_master_nfs.sh

# Copy GPKG to shared directory
cp your_data.gpkg /export/mimmo/es_2023_all.gpkg

# Update docker-compose.yml with your Master IP
nano docker-compose.yml
# Change:
#   --advertise-kafka-addr PLAINTEXT://<YOUR_MASTER_IP>:9092

# Start Redpanda
docker-compose up -d

# Verify Redpanda is running
docker logs redpanda
```

#### 2. Worker Node Setup

```bash
# On each worker machine
git clone https://github.com/yourusername/kafka-satellite-pipeline.git
cd kafka-satellite-pipeline

# (Optional) Create virtualenv
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install kafka-python geopandas stackstac pystac-client rasterio geocube pyogrio

# Mount NFS share
chmod +x mount_worker_nfs.sh
nano mount_worker_nfs.sh  # Update MASTER_IP if needed
./mount_worker_nfs.sh

# Verify mount
ls -la /mnt/mimmo/
```

***

## 🔧 Configuration

### Network Configuration

**Master IP**: `192.168.128.236` (example; change in all files if different)

Files to update if using different IP:

- `docker-compose.yml`: line with `--advertise-kafka-addr`  
- `setup_master_nfs.sh`: `SUBNET` variable  
- `mount_worker_nfs.sh`: `MASTER_IP` variable  
- `worker.py` / `worker_balanced.py`: `bootstrap_servers` parameter  

### Worker Configuration

Edit `worker.py` or `worker_balanced.py` for processing parameters:

```python
self.chip_size = 256                        # Output chip dimensions (pixels)
self.gpkg_path = "/mnt/mimmo/es_2023_all.gpkg"  # Input GPKG path
self.output_dir = "/mnt/mimmo/output"       # Output directory (NFS)
```

In `worker_balanced.py` the sampling probabilities per macro-class are:

```python
self.sampling_probs = {
    1: 0.20,  # Ulivi
    2: 0.80,  # Vigneti
    3: 1.00,  # Agrumi/Frutta
    4: 0.20,  # Mandorle/Bosco
    5: 0.15,  # Cereali
    6: 1.00,  # Leguminose
    7: 1.00,  # Ortaggi estivi
    8: 0.40   # Maggese/Suolo
}
```

***

## Kafka Topic & Group Management Commands

### Create / Recreate Topics

```bash
# Create topics (example: 15 partitions)
sudo docker exec -it redpanda rpk topic create satellite-tasks --partitions 15
sudo docker exec -it redpanda rpk topic create satellite-results --partitions 15

# List topics
sudo docker exec -it redpanda rpk topic list
```

### Delete & Reset Topics

```bash
# Delete existing topics
sudo docker exec -it redpanda rpk topic delete satellite-tasks
sudo docker exec -it redpanda rpk topic delete satellite-results

# Recreate with new partition count (example: 15)
sudo docker exec -it redpanda rpk topic create satellite-tasks --partitions 15
sudo docker exec -it redpanda rpk topic create satellite-results --partitions 15
```

### Consumer Group Status

```bash
# Describe worker consumer group
sudo docker exec -it redpanda rpk group describe satellite-workers
sudo docker exec -it redpanda rpk group describe satellite-workers -v
```

***

## Usage Workflow

### Initial Setup (One-time)

```bash
# === On Master ===
# Start Redpanda
docker-compose up -d

# Create Kafka topics (example: 10 partitions)
sudo docker exec -it redpanda rpk topic create satellite-tasks --partitions 10
sudo docker exec -it redpanda rpk topic create satellite-results --partitions 10

# Verify topics
sudo docker exec -it redpanda rpk topic list
```

If you need to change the number of partitions later:

```bash
# Delete and recreate 'satellite-tasks' with more partitions
sudo docker exec -it redpanda rpk topic delete satellite-tasks
sudo docker exec -it redpanda rpk topic create satellite-tasks --partitions 20
```

### Running the Pipeline

```bash
# === Step 1: Start Workers (on each worker machine) ===
# Balanced worker with sampling etc.
python3 worker_balanced.py 1
python3 worker_balanced.py 2
# ...
python3 worker_balanced.py N

# Logs:
# "Worker N started, waiting for tasks..."

# === Step 2: Start Monitor (on Master) ===
python3 monitor_balanced.py      # or monitor.py for basic mode

# === Step 3: Launch Processing (on Master) ===
python3 master_balanced.py       # or master.py for basic mode

# Master will:
# - Read GPKG
# - Generate tasks for grid cells with polygons
# - Publish tasks to Kafka topic 'satellite-tasks'

# Workers will immediately start processing in parallel
```

### Monitoring Progress

```bash
# View consumer group status and lag
sudo docker exec -it redpanda rpk group describe satellite-workers -v

# View latest results messages
sudo docker exec -it redpanda rpk topic consume satellite-results --num 10
```

### Resetting the Pipeline

```bash
# Delete all tasks and results (full reset)
sudo docker exec -it redpanda rpk topic delete satellite-tasks
sudo docker exec -it redpanda rpk topic delete satellite-results

# Recreate topics (example: 15 partitions)
sudo docker exec -it redpanda rpk topic create satellite-tasks --partitions 15
sudo docker exec -it redpanda rpk topic create satellite-results --partitions 15
```

***

## Data Processing Workflow

1. **Master (balanced)** reads the GeoPackage (`es_2023_all.gpkg`) and generates a geographic grid over Spain (e.g., step 0.05°).  
2. For each grid cell, the Master:
   - Queries the GPKG by bbox  
   - Maps EuroCrops categories to 8 target classes  
   - Filters out cells with too few target polygons  
   - Publishes a task JSON to `satellite-tasks` containing bbox, class distribution, sampling probs, target samples.  
3. **Kafka/Redpanda** distributes tasks across available workers via the `satellite-workers` consumer group.  
4. For each task, **WorkerBalanced**:
   - Reads polygons from the shared GPKG for that bbox  
   - Maps to `label_id` (1–8)  
   - Applies **probabilistic sampling** per class (`sampling_probs`)  
   - Downloads Sentinel-2 imagery via AWS Earth Search (STAC), with seasonal logic and cloud-cover filter  
   - Reprojects polygons to imagery CRS (e.g., EPSG:32630)  
   - Rasterizes labels (`make_geocube`) to produce masks  
   - Extracts 256×256 chips centered on polygon centroids  
   - Saves image chips and masks to shared NFS storage (`/mnt/mimmo/output/images`, `/mnt/mimmo/output/masks`)  
   - Publishes a result JSON to `satellite-results` with `chips_saved`, `chips_per_class`, `status`.  
5. **MonitorBalanced**:
   - Consumes `satellite-results`  
   - Aggregates chips per class vs. target_samples  
   - Displays progress per class, total chips, and can be used to decide when to stop workers.  

***

## Output Format

Generated dataset structure:

```text
/mnt/mimmo/
├── es_2023_all.gpkg            # Input (from Master)
└── output/
    ├── images/
    │   ├── worker1_task0_class3_chip0.tif   # 10-band Sentinel-2 (uint16)
    │   ├── worker1_task0_class5_chip1.tif
    │   ├── worker2_task5_class7_chip0.tif
    │   └── ...
    └── masks/
        ├── worker1_task0_class3_chip0.tif   # Single-band labels (uint8)
        ├── worker1_task0_class5_chip1.tif
        ├── worker2_task5_class7_chip0.tif
        └── ...
```

Per un check rapido del numero di chip generati:

```bash
cd /mnt/mimmo/output

echo "Images: $(ls images/*.tif 2>/dev/null | wc -l)"
echo "Masks:  $(ls masks/*.tif 2>/dev/null | wc -l)"
# Esempio:
# Images: 33018
# Masks:  33017
```

***

## Crop Classification Classes

The system maps EuroCrops agricultural types to 8 macro-classes:

| Class ID | Name (IT)         | Crop Types (Examples)                                |
|----------|-------------------|------------------------------------------------------|
| 1        | Ulivi             | Olive plantations                                    |
| 2        | Vigneti           | Vineyards, wine grapes                               |
| 3        | Agrumi/Frutta     | Citrus plantations, temperate/subtropical fruits    |
| 4        | Mandorle/Bosco    | Almonds, orchards, forests                          |
| 5        | Cereali Inv.      | Wheat (durum/soft), barley, oats, triticale         |
| 6        | Leguminose        | Beans, chickpeas, peas, lentils, vetches            |
| 7        | Ortaggi Estivi    | Tomato, melons, watermelon, potatoes, vegetables    |
| 8        | Maggese/Suolo     | Fallow land, bare arable land                       |

***

## Sentinel-2 Image Specification

### Image Bands (10 channels, 256×256 pixels, `uint16`)

1. Blue (B2) – 490 nm  
2. Green (B3) – 560 nm  
3. Red (B4) – 665 nm  
4. NIR (B8) – 842 nm  
5. Red Edge 1 (B5) – 705 nm  
6. Red Edge 2 (B6) – 740 nm  
7. Red Edge 3 (B7) – 783 nm  
8. NIR narrow (B8A) – 865 nm  
9. SWIR 1 (B11) – 1610 nm  
10. SWIR 2 (B12) – 2190 nm  

- **Spatial Resolution**: 10 meters/pixel  
- **CRS**: EPSG:32630 (WGS 84 / UTM zone 30N)  

***

