# worker.py
import json
import logging
from kafka import KafkaConsumer, KafkaProducer
import geopandas as gpd
import stackstac
import pystac_client
import rasterio
from rasterio.windows import Window
import numpy as np
import os
from geocube.api.core import make_geocube

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SatelliteDataWorker:
    def __init__(self, worker_id, bootstrap_servers='192.168.128.236:9092'):
        self.worker_id = worker_id
        
        # Consumer per ricevere task
        self.consumer = KafkaConsumer(
            'satellite-tasks',
            bootstrap_servers=[bootstrap_servers],
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id='satellite-workers',
            enable_auto_commit=True,
            session_timeout_ms=30000,       # 30s
            heartbeat_interval_ms=10000,    # 10s  
            max_poll_interval_ms=600000,    # 10min
            request_timeout_ms=90000,       # 90s ← MAGGIORE di session_timeout!
            connections_max_idle_ms=600000  # 10min
        )

        # Producer per pubblicare risultati
        self.producer = KafkaProducer(
            bootstrap_servers=[bootstrap_servers],
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        
        # Configurazione (usa path condiviso)
        self.gpkg_path = "/mnt/mimmo/es_2023_all.gpkg"
        self.output_dir = "/mnt/mimmo"
        self.chip_size = 256
        self.max_chips_per_cell = 5  # Limita chip per cella
        
        self.target_classes = {
            'olive_plantations': 1, 'vineyards_wine_vine_rebland_grapes': 2,
            'citrus_plantations': 3, 'fruit_temperate_climate': 3,
            'almond': 4, 'orchards_fruits': 4,
            'durum_hard_wheat': 5, 'common_soft_wheat': 5,
            'broad_beans_horse_beans': 6, 'chickpeas': 6,
            'tomato': 7, 'melons': 7,
            'fallow_land_not_crop': 8, 'bare_arable_land': 8
        }
        
        self.assets = ["blue", "green", "red", "nir", "rededge1", 
                      "rededge2", "rededge3", "nir08", "swir16", "swir22"]
    
    def get_sentinel_data(self, bbox):
        """Scarica dati Sentinel-2 per il bbox"""
        try:
            catalog = pystac_client.Client.open(
                "https://earth-search.aws.element84.com/v1"
            )
            search = catalog.search(
                collections=["sentinel-2-l2a"],
                bbox=bbox,
                datetime="2023-05-15/2023-06-30",
                query={"eo:cloud_cover": {"lt": 10}}
            )
            
            items = search.item_collection()
            if not len(items):
                logger.warning(f"No images found for bbox {bbox}")
                return None
            
            data = stackstac.stack(
                [items[0]], 
                assets=self.assets, 
                bounds_latlon=bbox, 
                resolution=10,
                epsg=32630, 
                fill_value=0, 
                rescale=False
            )
            
            if data.sizes['time'] == 0:
                return None
                
            return data.isel(time=0).astype("uint16").compute()
            
        except Exception as e:
            logger.error(f"Error downloading  {e}")
            return None
    
    def save_chip(self, img_arr, mask_arr, transform, crs, filename):
        """Salva chip e maschera su disco condiviso"""
        os.makedirs(f"{self.output_dir}/images", exist_ok=True)
        os.makedirs(f"{self.output_dir}/masks", exist_ok=True)
        
        with rasterio.open(
            f"{self.output_dir}/images/{filename}.tif", 'w',
            driver='GTiff', height=img_arr.shape[1], width=img_arr.shape[2],
            count=img_arr.shape[0], dtype='uint16', crs=crs, transform=transform
        ) as dst:
            dst.write(img_arr)
        
        with rasterio.open(
            f"{self.output_dir}/masks/{filename}.tif", 'w',
            driver='GTiff', height=mask_arr.shape[0], width=mask_arr.shape[1],
            count=1, dtype='uint8', nodata=0, crs=crs, transform=transform
        ) as dst:
            dst.write(mask_arr, 1)
    
    def process_task(self, task):
        """Processa una singola cella"""
        task_id = task['task_id']
        bbox = tuple(task['bbox'])
        
        logger.info(f"Worker {self.worker_id} processing task {task_id}: {bbox}")
        
        result = {
            'task_id': task_id,
            'worker_id': self.worker_id,
            'bbox': bbox,
            'chips_saved': 0,
            'status': 'success'
        }
        
        try:
            # Leggi poligoni nella bbox
            local_gdf = gpd.read_file(self.gpkg_path, bbox=bbox)
            
            if len(local_gdf) < 5:
                result['status'] = 'skipped_few_polygons'
                return result
            
            # Mappa classi
            local_gdf['label_id'] = local_gdf['EC_hcat_n'].map(self.target_classes)
            target_polys = local_gdf.dropna(subset=['label_id'])
            
            if len(target_polys) == 0:
                result['status'] = 'skipped_no_target_classes'
                return result
            
            # Scarica dati satellitari
            da = self.get_sentinel_data(bbox)
            if da is None:
                result['status'] = 'failed_download'
                return result
            
            # Riproiezione
            if local_gdf.crs != da.rio.crs:
                local_gdf = local_gdf.to_crs(da.rio.crs)
                target_polys = target_polys.to_crs(da.rio.crs)
            
            # Genera maschera
            cube = make_geocube(
                vector_data=local_gdf, 
                measurements=["label_id"], 
                like=da, 
                fill=0
            )
            
            img_np = da.to_numpy()
            mask_np = cube.label_id.to_numpy().astype("uint8")
            transform = da.rio.transform()
            
            if np.max(mask_np) == 0:
                result['status'] = 'failed_empty_mask'
                return result
            
            # Estrai chip
            chips_saved = 0
            for _, row in target_polys.iterrows():
                if chips_saved >= self.max_chips_per_cell:
                    break
                
                cx, cy = ~transform * (row.geometry.centroid.x, row.geometry.centroid.y)
                cx, cy = int(cx), int(cy)
                
                min_x = cx - self.chip_size // 2
                max_x = cx + self.chip_size // 2
                min_y = cy - self.chip_size // 2
                max_y = cy + self.chip_size // 2
                
                if (min_x < 0 or min_y < 0 or 
                    max_x > img_np.shape[2] or max_y > img_np.shape[1]):
                    continue
                
                im_c = img_np[:, min_y:max_y, min_x:max_x]
                mk_c = mask_np[min_y:max_y, min_x:max_x]
                
                if np.mean(im_c) > 0 and mk_c[self.chip_size//2, self.chip_size//2] > 0:
                    filename = f"worker{self.worker_id}_task{task_id}_chip{chips_saved}"
                    self.save_chip(
                        im_c, mk_c,
                        rasterio.windows.transform(
                            Window(min_x, min_y, self.chip_size, self.chip_size), 
                            transform
                        ),
                        da.rio.crs,
                        filename
                    )
                    chips_saved += 1
            
            result['chips_saved'] = chips_saved
            logger.info(f"Task {task_id} completed: {chips_saved} chips saved")
            
        except Exception as e:
            logger.error(f"Error processing task {task_id}: {e}")
            result['status'] = 'failed'
            result['error'] = str(e)
        
        return result
    
    def start(self):
        logger.info(f"Worker {self.worker_id} started, waiting for tasks...")
        
        try:
            while True:
                # Poll ESPLICITO con timeout - dà tempo al rebalancing
                msg_pack = self.consumer.poll(timeout_ms=1000)  
                
                for topic_partition, messages in msg_pack.items():
                    for message in messages:
                        task = message.value
                        result = self.process_task(task)
                        self.producer.send('satellite-results', value=result)
                        self.producer.flush()
                        
                        # COMMIT ESPLICITO dopo ogni task
                        self.consumer.commit()
                        
        except KeyboardInterrupt:
            logger.info(f"Worker {self.worker_id} stopping...")
        finally:
            self.consumer.close()
            self.producer.close()

if __name__ == "__main__":
    import sys
    worker_id = sys.argv[1] if len(sys.argv) > 1 else "1"
    worker = SatelliteDataWorker(worker_id)
    worker.start()
