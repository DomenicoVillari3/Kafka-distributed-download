# master.py (CON LETTURA GPKG)
import json
from kafka import KafkaProducer
import geopandas as gpd
import logging
from shapely.geometry import box

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SatelliteDataMaster:
    def __init__(self, bootstrap_servers='localhost:9092'):
        self.producer = KafkaProducer(
            bootstrap_servers=[bootstrap_servers],
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda k: k.encode('utf-8') if k else None
        )
        self.topic = 'satellite-tasks'
        self.gpkg_path = "/export/mimmo/es_2023_all.gpkg"  # Path condiviso
    
    def generate_tasks_from_gpkg(self, start_x, start_y, grid_step, x_cells, y_cells):
        """Legge GPKG e genera task solo per celle con poligoni"""
        logger.info(f"Reading GPKG: {self.gpkg_path}")
        
        # Leggi solo bounds e CRS (veloce, non carica geometrie)
        gdf_meta = gpd.read_file(self.gpkg_path, rows=1)
        logger.info(f"GPKG CRS: {gdf_meta.crs}")
        
        tasks = []
        task_id = 0
        
        for i in range(x_cells):
            for j in range(y_cells):
                x = start_x + (i * grid_step)
                y = start_y + (j * grid_step)
                cell_bbox = (x, y, x + grid_step, y + grid_step)
                
                # LEGGE GPKG solo per questa bbox (spatial filter efficiente)
                try:
                    local_gdf = gpd.read_file(self.gpkg_path, bbox=cell_bbox)
                    
                    # Salta celle vuote o con pochi poligoni
                    if len(local_gdf) < 5:
                        logger.debug(f"Skipping cell {cell_bbox}: only {len(local_gdf)} polygons")
                        continue
                    
                    logger.info(f"Cell {cell_bbox}: {len(local_gdf)} polygons → creating task")
                    
                    task = {
                        'task_id': task_id,
                        'bbox': cell_bbox,
                        'grid_step': grid_step,
                        'polygon_count': len(local_gdf)  # Info extra
                    }
                    tasks.append(task)
                    task_id += 1
                    
                except Exception as e:
                    logger.warning(f"Error reading cell {cell_bbox}: {e}")
                    continue
        
        logger.info(f"Generated {len(tasks)} tasks from {x_cells*y_cells} cells")
        return tasks
    
    def publish_tasks(self, tasks):
        """Pubblica i task sul topic Kafka"""
        logger.info(f"Publishing {len(tasks)} tasks to Kafka...")
        
        for task in tasks:
            self.producer.send(
                self.topic,
                key=f"task_{task['task_id']}",
                value=task
            )
            logger.debug(f"Published task {task['task_id']}: {task['bbox']}")
        
        self.producer.flush()
        logger.info(f"All {len(tasks)} tasks published successfully")
    
    def run(self):
        # Configurazione area (Siviglia)
        start_x, start_y = -5.80, 37.20
        grid_step = 0.05
        x_cells = 10
        y_cells = 10
        
        # Genera task leggendo GPKG
        tasks = self.generate_tasks_from_gpkg(start_x, start_y, grid_step, x_cells, y_cells)
        
        if len(tasks) == 0:
            logger.error("No tasks generated! Check GPKG path and area coverage")
            return
        
        # Pubblica su Kafka
        self.publish_tasks(tasks)
        
        self.producer.close()
        logger.info("Master completed")

if __name__ == "__main__":
    master = SatelliteDataMaster()
    master.run()
