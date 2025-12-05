Perfetto! Ecco il README completo basato sui tuoi file definitivi:

```markdown
# Kafka Satellite Data Pipeline

A distributed processing system for generating crop classification datasets from Sentinel-2 satellite imagery using Apache Kafka/Redpanda for task distribution across multiple worker nodes [web:22][web:30].

## 📋 Overview

This project implements a scalable pipeline for downloading and processing satellite imagery based on agricultural field polygons stored in GeoPackage format. The system uses Kafka/Redpanda to distribute workload across multiple worker machines, enabling parallel processing of large geographic areas [web:30].

### Key Features

- **Distributed Processing**: Kafka-based task queue for parallel execution across multiple workers
- **Sentinel-2 Integration**: Automated download from AWS Earth Search STAC API
- **Geospatial Processing**: Polygon-based chip extraction with mask generation
- **Fault Tolerance**: Automatic task rebalancing if workers fail
- **Real-time Monitoring**: Progress tracking through dedicated monitor component
- **Scalable**: Add/remove workers dynamically without interrupting processing
- **NFS Storage**: Shared filesystem for coordinated data access across nodes



## 🚀 Quick Start

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
pip install kafka-python geopandas stackstac pystac-client rasterio geocube pyogrio shapely

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

## 📦 Project Structure

```
kafka-satellite-pipeline/
├── docker-compose.yml       # Redpanda broker configuration
├── setup_master_nfs.sh      # NFS server setup script (Master)
├── mount_worker_nfs.sh      # NFS client mount script (Workers)
├── master.py                # Task generator and publisher
├── worker.py                # Task consumer and processor
├── monitor.py               # Progress tracking (optional)
├── test_generate_dataset.py # Original sequential implementation
├── requirements.txt         # Python dependencies
└── README.md
```

## 🔧 Configuration

### Network Configuration

**Master IP**: `192.168.128.236` (default, change in all files if different)

Files to update if using different IP [file:33][file:37]:
- `docker-compose.yml`: Line with `--advertise-kafka-addr`
- `setup_master_nfs.sh`: SUBNET variable
- `mount_worker_nfs.sh`: MASTER_IP variable
- `worker.py`: `bootstrap_servers` parameter

### Processing Area Configuration

Edit `master.py` to configure geographic area [file:36]:

```
# In master.py, method run():
start_x, start_y = -5.80, 37.20  # Southwest corner (Seville, Spain)
grid_step = 0.05                 # Cell size (~5.5 km)
x_cells = 10                     # Number of cells in X direction
y_cells = 10                     # Number of cells in Y direction
```

### Worker Configuration

Edit `worker.py` for processing parameters [file:37]:

```
self.chip_size = 256              # Output chip dimensions (pixels)
self.max_chips_per_cell = 5       # Maximum chips per geographic cell
self.gpkg_path = "/mnt/mimmo/es_2023_all.gpkg"  # Input GPKG path
self.output_dir = "/mnt/mimmo"    # Output directory
```

## 🎯 Usage Workflow

### Initial Setup (One-time)

```
# === On Master ===
# Start Redpanda
docker-compose up -d

# Create Kafka topics with 10 partitions
sudo docker exec -it redpanda rpk topic create satellite-tasks --partitions 10
sudo docker exec -it redpanda rpk topic create satellite-results --partitions 1

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

# Run master again
python3 master.py
```

## 📊 Data Processing Workflow

1. **Master** reads GeoPackage and generates geographic grid (e.g., 10×10 = 100 cells) [file:36]
2. **Master** filters cells with at least 5 polygons
3. **Master** publishes task JSON for each valid cell to Kafka topic `satellite-tasks`
4. **Kafka** distributes tasks across available workers using consumer group load balancing
5. For each task, **Worker** [file:37]:
   - Reads polygons from GeoPackage for the cell bbox
   - Downloads Sentinel-2 imagery (2023-05-15 to 2023-06-30, cloud cover <10%)
   - Reprojects polygons to match imagery CRS (EPSG:32630)
   - Generates rasterized masks using GeoCube
   - Extracts 256×256 chips centered on field centroids
   - Saves chips and masks to shared NFS storage
   - Publishes result to `satellite-results` topic
6. **Monitor** tracks progress and aggregates statistics [file:34]

## 🎯 Crop Classification Classes

The system maps EuroCrops agricultural types to 8 classes [file:37]:

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

## 📄 Output Format

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

## 🔍 Diagnostics and Troubleshooting

### Check Kafka Connection

```
# From any machine
telnet 192.168.128.236 9092
nc -zv 192.168.128.236 9092
```

### Check NFS Mount

```
# On workers
df -h | grep mimmo
ls -la /mnt/mimmo/

# On master
showmount -e localhost
```

### View Redpanda Logs

```
docker logs redpanda -f
```

### Common Issues

**Problem**: Workers can't connect - `KafkaConnectionError: 111 ECONNREFUSED`

**Solution**: 
- Verify `--advertise-kafka-addr` in `docker-compose.yml` matches Master IP [file:33]
- Check firewall: `sudo ufw allow 9092/tcp`
- Restart Redpanda: `docker-compose restart`

**Problem**: `FileNotFoundError: es_2023_all.gpkg`

**Solution**: 
- Verify NFS mount: `mountpoint /mnt/mimmo`
- Check file exists on master: `ls /export/mimmo/`
- Remount: `sudo mount 192.168.128.236:/export/mimmo /mnt/mimmo`

**Problem**: Workers stuck on "Re-joining group"

**Solution**: 
- Normal during startup (5-10 seconds)
- Wait for `Successfully joined group satellite-workers` message
- Check consumer group: `sudo docker exec -it redpanda rpk group describe satellite-workers`

**Problem**: "No images found for bbox"

**Solution**: 
- Area/timeframe may have no Sentinel-2 data
- Adjust datetime in `worker.py`: `datetime="2023-05-15/2023-06-30"`
- Increase cloud cover threshold: `query={"eo:cloud_cover": {"lt": 20}}`

## 📈 Performance Tuning

### Scale Workers

```
# Add more workers on existing machines
python3 worker.py 4 &
python3 worker.py 5 &

# Or add new worker machines
# Follow "Worker Node Setup" on new machines
```

### Increase Partitions

More partitions = more parallel workers supported [web:30]:

```
# Delete and recreate topic with more partitions
sudo docker exec -it redpanda rpk topic delete satellite-tasks
sudo docker exec -it redpanda rpk topic create satellite-tasks --partitions 20
```

### Adjust Processing Parameters

```
# In worker.py - process more chips per cell
self.max_chips_per_cell = 10

# In master.py - larger cells
grid_step = 0.1  # ~11 km cells
```

### Monitor Resource Usage

```
# On workers
htop
nvidia-smi  # If using GPU (requires GPU-enabled stackstac)

# Network traffic
iftop
```

## 📚 Dependencies

```
kafka-python>=2.0.2        # Kafka client
geopandas>=0.14.0          # Geospatial data handling
stackstac>=0.5.0           # STAC data loading
pystac-client>=0.7.0       # STAC catalog access
rasterio>=1.3.0            # Raster I/O
geocube>=0.4.0             # Vector to raster conversion
pyogrio>=0.7.0             # Fast spatial filtering
numpy>=1.24.0              # Array operations
shapely>=2.0.0             # Geometric operations
```

Install all:
```
pip install -r requirements.txt
```

## 🤝 Contributing

Contributions welcome! Areas for improvement:
- Support for additional satellite sources (Landsat, Planet)
- Multi-temporal chip extraction
- On-the-fly augmentation
- Cloud-optimized GeoTIFF output
- S3/cloud storage backend

## 📝 License

This project is licensed under the MIT License.

## 🙏 Acknowledgments

- **Sentinel-2** data from AWS Open Data Program
- **Redpanda** for Kafka-compatible streaming platform
- **EuroCrops** for agricultural field polygons
- **GeoCube** for vector-to-raster conversion
- **stackstac** for efficient satellite data loading

## 📚 References

- [Sentinel-2 on AWS](https://registry.opendata.aws/sentinel-2/)
- [Redpanda Documentation](https://docs.redpanda.com/)
- [Apache Kafka Documentation](https://kafka.apache.org/documentation/)
- [STAC Specification](https://stacspec.org/)
- [EuroCrops Dataset](https://github.com/maja601/EuroCrops)

## 📧 Contact

For questions or issues, please open an issue on GitHub.

---
