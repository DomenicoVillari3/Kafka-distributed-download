# worker_balanced.py (BASATO SU CODICE FUNZIONANTE)
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
import time
import random


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SatelliteDataWorkerBalanced:
    def __init__(self, worker_id, bootstrap_servers='192.168.128.236:9092'):
        self.worker_id = worker_id
        
        # Consumer per ricevere task
        self.consumer = KafkaConsumer(
            'satellite-tasks',
            bootstrap_servers=[bootstrap_servers],
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            group_id='satellite-workers',
            
            # Auto-commit
            enable_auto_commit=False,
            
            # Timeout
            session_timeout_ms=60000,
            heartbeat_interval_ms=20000,
            max_poll_interval_ms=1800000,
            request_timeout_ms=120000,
            
            # *** KEEP-ALIVE & RECONNECTION ***
            connections_max_idle_ms=540000,  # 9min (prima scadenza server 10min)
            reconnect_backoff_ms=50,         # Retry veloce
            reconnect_backoff_max_ms=1000,   # Max 1s tra retry
            retry_backoff_ms=100,
            
            # *** SOCKET OPTIONS per keep-alive TCP ***
            api_version_auto_timeout_ms=3000,
            metadata_max_age_ms=300000,  # Refresh metadata ogni 5min
            
        )
        
        # Producer per pubblicare risultati
        self.producer = KafkaProducer(
            bootstrap_servers=[bootstrap_servers],
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        
        # Configurazione
        self.gpkg_path = "/mnt/mimmo/es_2023_all.gpkg"
        self.output_dir = "/mnt/mimmo/output"
        self.chip_size = 256
        
        # Sampling probabilities (verranno aggiornate dal task)
        self.sampling_probs = {
            1: 0.20, 2: 0.80, 3: 1.00, 4: 0.20,
            5: 0.15, 6: 1.00, 7: 1.00, 8: 0.40
        }
        
        # Mappatura classi
        self.target_classes = {
            'olive_plantations': 1,
            'vineyards_wine_vine_rebland_grapes': 2,
            'citrus_plantations': 3, 'fruit_temperate_climate': 3,
            'fruit_subtropical_climate': 3,
            'almond': 4, 'orchards_fruits': 4, 'tree_wood_forest': 4,
            'other_tree_wood_forest': 4,
            'durum_hard_wheat': 5, 'common_soft_wheat': 5, 'barley': 5,
            'oats': 5, 'triticale': 5,
            'broad_beans_horse_beans': 6, 'chickpeas': 6, 'peas': 6,
            'lentils': 6, 'vetches': 6,
            'tomato': 7, 'melons': 7, 'watermelon': 7, 'potatoes': 7,
            'vegetables_fresh': 7,
            'fallow_land_not_crop': 8, 'bare_arable_land': 8
        }
        
        # Nel __init__ del Worker
        self.assets = [
            "blue",    # B02
            "green",   # B03
            "red",     # B04
            "nir08",   # B8A (Narrow NIR richiesto da Prithvi)
            "swir16",  # B11
            "swir22"   # B12
        ]
    
    def get_sentinel_data(self, bbox):
        """Scarica una serie temporale di 4 immagini Sentinel-2 (6 bande) per Prithvi"""
        
        # 1. Definiamo i 4 periodi (uno per stagione)
        # Usiamo date fisse del 2023 per coerenza tra tutti i worker
        seasonal_periods = {
            'winter': "2023-01-01/2023-02-28",
            'spring': "2023-04-15/2023-05-30",
            'summer': "2023-07-01/2023-08-15",
            'autumn': "2023-10-01/2023-11-15"
        }
        
        # Ordine temporale rigoroso per il cubo 4D
        ordered_seasons = ['winter', 'spring', 'summer', 'autumn']
        
        # Usiamo solo le 6 bande richieste da Prithvi
        # Assicurati che self.assets nel costruttore sia: 
        # ["blue", "green", "red", "nir08", "swir16", "swir22"]
        
        stac_items = []
    
        try:
            catalog = pystac_client.Client.open("https://earth-search.aws.element84.com/v1")
            
            for season in ordered_seasons:
                date_range = seasonal_periods[season]
                
                # Cerchiamo l'immagine migliore per la stagione
                search = catalog.search(
                    collections=["sentinel-2-l2a"],
                    bbox=bbox,
                    datetime=date_range,
                    query={"eo:cloud_cover": {"lt": 20}} # Max 20% nuvole
                )
                
                items = search.item_collection()
                
                if not len(items):
                    # Se manca anche una sola stagione, il "cubo temporale" è incompleto
                    logger.warning(f"Manca immagine per {season} in {bbox}. Task scartato.")
                    return None
                
                # Prendiamo quella con meno nuvole
                best_item = min(items, key=lambda x: x.properties['eo:cloud_cover'])
                stac_items.append(best_item)
                
            # 2. Carichiamo tutte e 4 le immagini insieme come un unico cubo
            # stackstac creerà una dimensione 'time' di dimensione 4
            data = stackstac.stack(
                stac_items,
                assets=self.assets,
                bounds_latlon=bbox,
                resolution=10,
                epsg=32630, # UTM zone 30N (adatta per Spagna/Ovest Europa)
                fill_value=0,
                rescale=False
            )
            
            # 3. Controllo integrità e computazione
            # Shape attesa: (time: 4, band: 6, y: 256, x: 256)
            if data.sizes['time'] < 4:
                return None
                
            logger.info(f" ✓ Download completato per 4 stagioni su bbox {bbox}")
            
            # Ritorniamo il cubo NumPy [T, C, H, W]
            return data.astype("uint16").compute().values
        
        except Exception as e:
            logger.error(f"Errore durante il download multi-temporale: {e}")
            return None
    
    def save_chip(self, img_cube, mask_arr, filename):
        """Salva il cubo 4D come .npy e la maschera come .tif"""
        os.makedirs(f"{self.output_dir}/images", exist_ok=True)
        os.makedirs(f"{self.output_dir}/masks", exist_ok=True)
        
        # img_cube shape: (4, 6, 256, 256)
        # Salvataggio immagine in formato binario NumPy (veloce e mantiene le 4D)
        np.save(f"{self.output_dir}/images/{filename}.npy", img_cube.astype("uint16"))
        
        # La maschera rimane .tif (2D)
        with rasterio.open(
            f"{self.output_dir}/masks/{filename}.tif", 'w',
            driver='GTiff', height=mask_arr.shape[0], width=mask_arr.shape[1],
            count=1, dtype='uint8', nodata=0, crs="EPSG:32630", 
            transform=rasterio.transform.from_origin(0,0,1,1) # dummy transform
        ) as dst:
            dst.write(mask_arr, 1)
        
    def process_task(self, task):
        """Versione Multi-temporale (T=4): Scarica 4 stagioni ed estrae chip 4D"""
        task_id = task['task_id']
        bbox = tuple(task['bbox'])
        
        # Aggiorna sampling probs
        if 'sampling_probs' in task:
            self.sampling_probs = {int(k): v for k, v in task['sampling_probs'].items()}
        
        logger.info(f"Worker {self.worker_id} processing task {task_id}: {bbox}")
        
        result = {
            'task_id': task_id,
            'worker_id': self.worker_id,
            'bbox': bbox,
            'chips_saved': 0,
            'chips_per_class': {},
            'status': 'success',
            'target_samples': task.get('target_samples', {}),
            'sampling_probs': task.get('sampling_probs', {})
        }

        try:
            # 1. Leggi poligoni
            local_gdf = gpd.read_file(self.gpkg_path, bbox=bbox)
            if len(local_gdf) < 3:
                result['status'] = 'skipped_few_polygons'
                return result
            
            local_gdf['label_id'] = local_gdf['EC_hcat_n'].map(self.target_classes)
            local_gdf = local_gdf.dropna(subset=['label_id'])
            
            if len(local_gdf) == 0:
                result['status'] = 'skipped_no_target_classes'
                return result
            
            # 2. Filtro probabilistico
            probs = local_gdf['label_id'].map(self.sampling_probs).fillna(0)
            local_gdf['save_me'] = probs >= np.random.rand(len(local_gdf))
            target_polys = local_gdf[local_gdf['save_me']]
            
            if len(target_polys) == 0:
                result['status'] = 'skipped_sampling'
                return result
            
            # 3. Scarica dati satellitari (MODIFICATO PER T=4)
            # Assumiamo che get_sentinel_data restituisca il DataArray di stackstac con 4 step temporali
            da = self.get_sentinel_data(bbox)
            if da is None:
                result['status'] = 'failed_download'
                return result
            
            # 4. Riproiezione e Allineamento
            if local_gdf.crs != da.rio.crs:
                local_gdf = local_gdf.to_crs(da.rio.crs)
                target_polys = target_polys.to_crs(da.rio.crs)
            
            # 5. Genera Maschera (2D)
            # Usiamo il primo step temporale di 'da' come riferimento spaziale
            cube = make_geocube(
                vector_data=local_gdf,
                measurements=["label_id"],
                like=da.isel(time=0), 
                fill=0
            )
            
            # 6. Conversione in NumPy
            # img_np shape: (4, 6, H, W) -> [Tempo, Bande, H, W]
            img_np = da.to_numpy()
            # mask_np shape: (H, W)
            mask_np = cube.label_id.fillna(0).to_numpy().astype("uint8")
            
            transform = da.rio.transform()
            
            if np.max(mask_np) == 0:
                result['status'] = 'failed_empty_mask'
                return result
            
            # 7. Estrazione Chip
            chips_saved = 0
            chips_per_class = {}
            
            for _, row in target_polys.iterrows():
                # Coordinate pixel dal centroide del poligono
                cx, cy = ~transform * (row.geometry.centroid.x, row.geometry.centroid.y)
                cx, cy = int(cx), int(cy)
                
                min_x = cx - self.chip_size // 2
                max_x = cx + self.chip_size // 2
                min_y = cy - self.chip_size // 2
                max_y = cy + self.chip_size // 2
                
                # Controllo bordi spaziali
                if (min_x < 0 or min_y < 0 or 
                    max_x > img_np.shape[3] or max_y > img_np.shape[2]):
                    continue
                
                # 🔥 SLICING 4D: [Tutti i tempi, Tutte le bande, Y, X]
                im_c = img_np[:, :, min_y:max_y, min_x:max_x]
                mk_c = mask_np[min_y:max_y, min_x:max_x]
                
                # Controllo integrità del cubo (deve avere 4 tempi e 6 bande)
                if im_c.shape == (4, 6, self.chip_size, self.chip_size):
                    # Verifica che il pixel centrale sia valido
                    if np.mean(im_c) > 0 and mk_c[self.chip_size//2, self.chip_size//2] > 0:
                        
                        class_id = int(mk_c[self.chip_size//2, self.chip_size//2])
                        filename = f"worker{self.worker_id}_task{task_id}_class{class_id}_chip{chips_saved}"
                        
                        # Salvataggio (la funzione save_chip deve ora gestire .npy per l'immagine)
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
                        chips_per_class[class_id] = chips_per_class.get(class_id, 0) + 1
            
            result['chips_saved'] = chips_saved
            result['chips_per_class'] = chips_per_class
            
            if chips_saved > 0:
                logger.info(f"  ✓ Task {task_id}: {chips_saved} chips multi-temporali salvati.")
                
        except Exception as e:
            logger.error(f"Error processing task {task_id}: {e}")
            result['status'] = 'failed'
            result['error'] = str(e)
        
        return result
        
    def start(self):
        """Avvia il worker"""
        logger.info(f"Worker {self.worker_id} started, waiting for tasks...")
        
        try:
            while True:
                # Poll con timeout
                msg_pack = self.consumer.poll(timeout_ms=1000)
                
                for topic_partition, messages in msg_pack.items():
                    for message in messages:
                        task = message.value
                        result = self.process_task(task)
                        
                        # Pubblica risultato
                        self.producer.send('satellite-results', value=result)
                        self.producer.flush()
                        
                        # Commit esplicito
                        self.consumer.commit()
                        
        except KeyboardInterrupt:
            logger.info(f"Worker {self.worker_id} stopping...")
        finally:
            self.consumer.close()
            self.producer.close()

if __name__ == "__main__":
    import sys
    intit_time = time.time()
    worker_id = sys.argv[1] if len(sys.argv) > 1 else "1"
    worker = SatelliteDataWorkerBalanced(worker_id)
    worker.start()
    end=time.time()-intit_time

    with open("/mnt/mimmo/worker_time.txt", "a") as f:
        f.write(f"Worker={worker_id} time={end} sec\n")
        f.close()
    
