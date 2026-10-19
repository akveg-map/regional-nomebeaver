# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Parse vegetation types
# Author: Timm Nawrocki
# Last Updated: 2026-10-17
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Parse vegetation types" runs a programmatic key to the AKVEG map classes using foliar cover and surficial features maps, as well as additional ancillary data.
# ---------------------------------------------------------------------------

# Set execution parameters
processors = 1
processor = 1
nodata_value = -32768

# Import packages
import os
import time
import math
import numpy as np
from osgeo import gdal
import geopandas as gpd
import rasterio
from rasterio import features
from google.cloud import storage
from akutils import *
from programmatic_keys.key_needleleaf import key_needleleaf
from programmatic_keys.key_broadleaf import key_broadleaf
from programmatic_keys.key_mixed import key_mixed
from programmatic_keys.key_tussock import key_tussock
from programmatic_keys.key_shrub import key_shrub
from programmatic_keys.key_herbaceous import key_herbaceous

# Configure GDAL
gdal.UseExceptions()

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
region_folder = os.path.join(project_folder, 'data_input/region_data')
region_geopackage = os.path.join(region_folder, 'region_data_3338.gpkg')
segment_folder = os.path.join(project_folder, 'data_input/segment_data')
surficial_folder = os.path.join(project_folder, 'data_output/surficial_data')
output_folder = os.path.join(output_folder, 'data_output/veg_types')
tile_folder = os.path.join(output_folder, 'tiles')

# Define input files
area_input = os.path.join(region_folder, 'nomebeaver_domain_2m_3338.tif')
grid_layer = 'tiles_001_3338'
zonal_input = os.path.join(segment_folder, 'zonal_stats_2m_3338.tif')
surficial_input = os.path.join(surficial_folder, 'surficial_2m_3338.tif')
peat_input = os.path.join(output_folder, 'peat_probability_2m_3338.tif')
fire_input = os.path.join(output_folder, 'fire_year_2m_3338.tif')
burned_input = os.path.join(output_folder, 'recently_burned_2m_3338.tif')

#### IDENTIFY PREDICTION GRIDS
####____________________________________________________

# Read grid data
grid_data = gpd.read_file(region_geopackage, layer=grid_layer)

# Define grid list
grid_list = grid_data['grid_code'].tolist()

# Partition grid list for spatially parallel processing
grid_chunks = np.array_split(grid_list, processors)
grid_list = grid_chunks[processor - 1].tolist()

# Create final grid data
grid_data = grid_data[grid_data['grid_code'].isin(grid_list)]
print(f'Predicting {len(grid_data)} grids...')

#### PARSE VEGETATION TYPES
####____________________________________________________

# Define zonal statistics sets
zonal_topo = ['coast', 'stream', 'river', 'wetness',
                  'elevation', 'exposure', 'heatload', 'position',
                  'aspect', 'relief', 'roughness', 'slope']
zonal_foliar = ['alnus', 'betshr', 'bettre', 'dryas', 'dsalix',
                    'empnig', 'erivag', 'feather', 'forb', 'gramin',
                    'lichen', 'mwcalama', 'ndsalix', 'neetre', 'nerishr',
                    'picgla', 'picmar', 'poptre', 'populbt', 'rhoshr',
                    'sphagn', 'vaculi', 'vacvit', 'wetforb', 'wetsed']
zonal_dist = ['bromos', 'wetgram']
zonal_sum = ['eridwarf', 'erishrub', 'herbac', 'ndshrub', 'shrub', 'trees', 'wetind']
zonal_ratio = ['deciduous_ratio', 'picea_ratio', 'tussock_ratio']

# Concatenate zonal_statistics sets
zonal_all = zonal_topo + zonal_foliar + zonal_dist + zonal_sum + zonal_ratio

# Identify band indices for zonal input raster
with rasterio.open(zonal_input) as src:
    raster_band_map = {desc: idx for idx, desc in enumerate(src.descriptions, start=1) if desc}
    try:
        selected_bands = [raster_band_map[name] for name in predictor_zonal]
    except KeyError as e:
        raise KeyError(f'Requested zonal predictor {e} was not found in raster band descriptions.')

# Rename zonal band handles
# deciduous_ratio = decratio
# tussock_ratio = tussock
# picea_ratio = picratio

#### POST-PROCESS TILES
####____________________________________________________

# Create a dictionary of input names and paths
raster_paths = {
    'area': area_input,
    'surficial': surficial_input,
    'peat': peat_input,
    'fire': fire_input,
    'burned': burned_input
}
# Add the selected_bands and raster_paths so that each dataset can be referenced by name

# Iterate through input paths to open them into a dictionary
raster_sources = {}
for name, path in raster_paths.items():
    raster_sources[name] = rasterio.open(path)

# Define grid alignment from area_input
area_transform = raster_sources['area'].transform
align_x = area_transform[2]
align_y = area_transform[5]
res_x = area_transform[0]
res_y = abs(area_transform[4])

# Post-process each grid in grid list
grid_count = 1
for index, row in grid_data.iterrows():
    # Define grid code
    grid = row['grid_code']

    # Define output paths
    veg_tile = os.path.join(tiles_folder, f'{grid}_2m_3338.tif')
    gcs_output = f'{gcs_base}/veg_types/tiles/{grid}_2m_3338.tif'

    # Create output raster if it does not already exist in GCS
    if not gcs_blob_exists(gcs_output, storage_client):
        print(f'Post-processing {grid} ({grid_count} of {len(grid_list)})...')
        start_time = time.time()

        # Define processing geometry
        geometry_processing = row['geometry'].buffer(200)
        left_processing, bottom_processing, right_processing, top_processing = geometry_processing.bounds
        left_processing = align_x + math.floor((left_processing - align_x) / res_x) * res_x
        bottom_processing = align_y + math.floor((bottom_processing - align_y) / res_y) * res_y
        right_processing = align_x + math.ceil((right_processing - align_x) / res_x) * res_x
        top_processing = align_y + math.ceil((top_processing - align_y) / res_y) * res_y

        # Define window bounds for processing
        window_processing = (left_processing, bottom_processing, right_processing, top_processing)

        # Define export geometry
        geometry_export = row['geometry'].buffer(10)
        left_export, bottom_export, right_export, top_export = geometry_export.bounds
        left_export = align_x + math.floor((left_export - align_x) / res_x) * res_x
        bottom_export = align_y + math.floor((bottom_export - align_y) / res_y) * res_y
        right_export = align_x + math.ceil((right_export - align_x) / res_x) * res_x
        top_export = align_y + math.ceil((top_export - align_y) / res_y) * res_y

        # Define the output profile by the export geometry
        dst_transform = rasterio.transform.from_origin(left_export, top_export, res_x, res_y)
        dst_width = int(round((right_export - left_export) / res_x))
        dst_height = int(round((top_export - bottom_export) / res_y))

        # Calculate offsets to slice the processing buffer to the export buffer
        col_offset = int(round((left_export - left_processing) / res_x))
        row_offset = int(round((top_processing - top_export) / res_y))

        # Define output profile
        output_profile = {
            'driver': 'GTiff',
            'height': dst_height,
            'width': dst_width,
            'count': 1,
            'dtype': 'int8',
            'crs': 'EPSG:3338',
            'transform': dst_transform,
            'nodata': nodata_value,
            'compress': 'lzw',
            'tiled': True,
            'blockxsize': 512,
            'blockysize': 512
        }

        # Parse types
        with rasterio.open(veg_tile, 'w', **output_profile) as dst:
            # Load raster data
            data = {}
            for name, src in raster_sources.items():
                data[name] = read_raster_block(src, window_processing)

            # Initialize empty arrays for the vegetation types
            base_data = np.zeros_like(data['area'], dtype=np.int16)

            #### KEY THE LAND COVER TYPES
            ####____________________________________________________

            # 1000. needleleaf trees
            base_data = np.where(
                (base_data == 0)
                & (((data['neetre'] >= 8) & (~np.isin(data['surficial'], [1, 2])))
                 | ((data['neetre'] >= 5) & (data['surficial'] == 3))
                 | ((data['neetre'] >= 5) & (data['fire'] >= 1980))
                 | ((data['neetre'] >= 5) & (data['lichen'] >= 35)))
                & (data['decratio'] < 40),
                1000, base_data)

            # 2000. broadleaf trees
            base_data = np.where(
                (base_data == 0)
                & ((data['brotre'] >= 10)
                   | ((data['brotre'] >= 5) & (data['fire'] >= 1980)))
                & (data['decratio'] >= 75) & (data['brotre'] >= (data['ndshrub'] * 0.5)),
                2000, base_data)

            # 3000. mixed trees
            base_data = np.where(
                (base_data == 0)
                & ((data['tree'] >= 10)
                   | ((data['tree'] >= 5) & (data['fire'] >= 1980)))
                & ((data['decratio'] >= 40) & (data['decratio'] < 75))
                & (data['tree'] >= (data['ndshrub'] * 0.5)),
                3000, base_data)

            # 4000. tussock
            base_data = np.where(
                (base_data == 0)
                & ((data['erivag'] >= 20)
                   | ((data['erivag'] >= 10) & (data['ndshrub'] < 40))
                   | ((data['erivag'] >= 8) & (data['ndshrub'] < 25) & (data['tussock'] >= 30))),
                4000, base_data)

            # 5000. shrub
            base_data = np.where(
                (((base_data == 0) & (data['shrub'] >= 20))
                 | ((base_data == 0) & (data['shrub'] >= 12) & (data['fire'] >= 1980))),
                5000, base_data)

            # 6000. herbaceous
            base_data = np.where(
                (base_data == 0)
                & ((data['herbac'] >= 20) | (data['sphagn'] >= 8) | (data['peat'] >= 38)),
                6000, base_data)

            # 995. ORV trail/disturbance
            base_data = np.where(
                data['surficial'] == 6,
                995, base_data)

            # 996. infrastructure
            base_data = np.where(
                data['surficial'] == 7,
                996, base_data)

            # 998. water
            base_data = np.where(
                data['surficial'] == 5,
                998, base_data)

            # 999. recently burned
            base_data = np.where(
                (np.isin(base_data, [0, 5000, 6000])) & (data['fire'] >= 2019),
                999, base_data)

            # 176. Alaska-Yukon Alpine Barren & Sparsely Vegetated
            base_data = np.where(
                data['surficial'] == 1,
                176, base_data)

            # 224. Alaska-Yukon Barren & Sparsely Vegetated Active Floodplain
            base_data = np.where(
                data['surficial'] == 9,
                224, base_data)

            # 250. Alaska-Yukon Barren & Sparsely Vegetated
            base_data = np.where(
                data['surficial'] == 4,
                250, base_data)

            #### KEY THE FRESHWATER MARSH TYPES
            ####____________________________________________________

            # 228. Alaska-Yukon Freshwater Marsh


            #### KEY MOISTURE REGIMES
            ####____________________________________________________

            # 1001. Needleleaf Mesic
            base_data = np.where(
                (base_data == 1000)
                & (data['wetind'] < 15) & (data['wetforb'] < 20) & (data['erivag'] < 12)
                & (data['wetgram'] < 50),
                1001, base_data)

            # 1002. Needleleaf Wet
            base_data = np.where(
                (base_data == 1000)
                & ((data['wetind'] >= 15) | (data['wetforb'] >= 20) | (data['erivag'] >= 12)
                   | (data['wetgram'] >= 50)),
                1002, base_data)

            # 5001. Shrub Mesic
            base_data = np.where(
                (base_data == 5000)
                & (data['wetind'] < 15) & (data['wetsed'] < 10)
                & (data['wetforb'] < 20) & (data['wetgram'] < 50)
                & (data['sphagn'] < 20) & (data['peat'] < 38),
                5001, base_data)

            # 5002. Shrub Wet
            base_data = np.where(
                (base_data == 5000)
                & ((data['wetind'] >= 15) | (data['wetsed'] >= 10)
                   | (data['wetforb'] >= 20) | (data['wetgram'] >= 50))
                & (data['sphagn'] < 20) & (data['peat'] < 38),
                5002, base_data)

            # 5003. Shrub Peat
            base_data = np.where(
                (base_data == 5000)
                & ((data['sphagn'] >= 20) | (data['peat'] >= 38)),
                5003, base_data)

            # 6001. Herbaceous Mesic
            base_data = np.where(
                (base_data == 6000)
                & (data['wetind'] < 15) & (data['wetsed'] < 10)
                & (data['wetforb'] < 20) & (data['wetgram'] < 50)
                & (data['sphagn'] < 20) & (data['peat'] < 38),
                6001, base_data)

            # 6002. Herbaceous Wet
            base_data = np.where(
                (base_data == 6000)
                & ((data['wetind'] >= 15) | (data['wetsed'] >= 10) | (data['wetforb'] >= 20)
                   | (data['wetgram'] >= 50))
                & (data['sphagn'] < 20) & (data['peat'] < 38),
                6002, base_data)

            # 6003. Herbaceous Peat
            base_data = np.where(
                (base_data == 6000)
                & ((data['sphagn'] >= 20) | (data['peat'] >= 38)),
                6003, base_data)

            #### KEY BOREAL MESIC NEEDLELEAF TYPES
            ####____________________________________________________

            # 212. Alaska-Yukon White Spruce Active Floodplain
            base_data = np.where(
                (base_data == 1001) & (data['surficial'] == 8)
                & (data['picgla'] >= 8) & (data['picratio'] >= 70),
                212, base_data)

            # 154. Alaska-Yukon Spruce-Lichen Woodland Mesic
            base_data = np.where(
                (base_data == 1001)
                & (data['lichen'] >= 35) & ((data['picgla'] >= 3) | (data['picmar'] >= 3)),
                154, base_data)

            # 155. Alaska-Yukon White Spruce Woodland Mesic
            base_data = np.where(
                (base_data == 1001)
                & (data['neetre'] < 20) & (data['picratio'] >= 60),
                155, base_data)

            # 151. Alaska-Yukon Black Spruce Woodland Mesic
            base_data = np.where(
                (base_data == 1001)
                & (data['neetre'] < 20) & (data['picratio'] < 40),
                151, base_data)

            # 152. Alaska-Yukon Mixed Spruce Woodland Mesic
            base_data = np.where(
                (base_data == 1001)
                & (data['neetre'] < 20) & (data['picratio'] >= 40) & (data['picratio'] < 60),
                152, base_data)

            # 117. Alaska-Yukon White Spruce Forest Mesic (Central)
            base_data = np.where(
                (base_data == 1001)
                & (data['picgla'] >= 3) & (data['neetre'] >= 20) & (data['picratio'] >= 60),
                117, base_data)

            # 112. Alaska-Yukon Black Spruce Forest Mesic (Central)
            base_data = np.where(
                (base_data == 1001)
                & (data['picmar'] >= 3) & (data['neetre'] >= 20) & (data['picratio'] < 40),
                112, base_data)

            # 114. Alaska-Yukon Mixed Spruce Forest Mesic (Central)
            base_data = np.where(
                (base_data == 1001)
                & (data['picmar'] >= 3) & (data['picgla'] >= 3) & (data['neetre'] >= 20)
                & (data['picratio'] >= 40) & (data['picratio'] < 60),
                114, base_data)

            #### KEY BOREAL WET NEEDLELEAF TYPES
            ####____________________________________________________

            # 203. Alaska-Yukon Black Spruce-Tussock Peatland, Ombrotrophic
            base_data = np.where(
                (base_data == 1002)
                & (data['picmar'] >= 3) & (data['picratio'] < 60) & (data['erivag'] >= 8),
                203, base_data)

            # 202. Alaska-Yukon Black Spruce Peatland, Ombrotrophic
            base_data = np.where(
                (base_data == 1002)
                & ((data['sphagn'] >= 20) | (data['wetsed'] >= 10) | (data['peat'] >= 38))
                & (data['picmar'] >= 3) & (data['picratio'] < 60),
                202, base_data)

            # 211. Alaska-Yukon Black Spruce Forest Wet
            base_data = np.where(
                (base_data == 1002)
                & (data['picmar'] >= 3) & (data['picratio'] < 60),
                211, base_data)

            #### KEY BOREAL MIXED FOREST TYPES
            ####____________________________________________________

            # 213. Birch (-White Spruce) Active Floodplain
            base_data = np.where(
                (base_data == 3000) & (data['surficial'] == 8)
                & (data['bettre'] >= 3)
                & (data['populbt'] < (data['bettre'] * 0.8)) & (data['bettre'] >= data['poptre']),
                213, base_data)

            # 214. Poplar (-White Spruce) Active Floodplain
            base_data = np.where(
                (base_data == 3000) & (data['surficial'] == 8)
                & (data['populbt'] >= 3)
                & (data['populbt'] >= (data['bettre'] * 0.8)) & (data['populbt'] >= data['poptre']),
                214, base_data)

            # 163. Alaska-Yukon Post-burn Recovering Aspen Forest Mesic
            base_data = np.where(
                (base_data == 3000) & (data['fire'] >= 1990)
                & (data['poptre'] >= 3)
                & (data['bettre'] < data['poptre']) & (data['populbt'] < data['poptre']),
                163, base_data)

            # 116. Alaska-Yukon Post-burn Recovering Birch Forest Mesic (Central)
            base_data = np.where(
                (base_data == 3000) & (data['fire'] >= 1990)
                & (data['bettre'] >= 3)
                & (data['bettre'] >= data['populbt']) & (data['bettre'] >= data['poptre']),
                116, base_data)

            # 113. Alaska-Yukon Black Spruce-Deciduous Forest Mesic (Central)
            base_data = np.where(
                (base_data == 3000)
                & (data['brotre'] >= 3) & (data['picmar'] >= 3) & (data['picratio'] < 40),
                113, base_data)

            # 115. Alaska-Yukon Mixed Spruce-Deciduous Forest Mesic (Central)
            base_data = np.where(
                (base_data == 3000)
                & (data['brotre'] >= 3) & (data['picmar'] >= 3) & (data['picgla'] >= 3)
                & (data['picratio'] >= 40) & (data['picratio'] < 60),
                115, base_data)

            # 118. Alaska-Yukon White Spruce-Aspen Forest Mesic (Central)
            base_data = np.where(
                (base_data == 3000)
                & (data['poptre'] >= 3) & (data['picgla'] >= 3) & (data['picratio'] >= 60)
                & (data['bettre'] < data['poptre']) & (data['populbt'] < data['poptre']),
                118, base_data)

            # 120. Alaska-Yukon White Spruce-Poplar Forest Mesic (Central)
            base_data = np.where(
                (base_data == 3000)
                & (data['populbt'] >= 3) & (data['picgla'] >= 3) & (data['picratio'] >= 60)
                & (data['populbt'] >= data['poptre']) & (data['bettre'] < data['populbt']),
                120, base_data)

            # 119. Alaska-Yukon White Spruce-Birch Forest Mesic (Central)
            base_data = np.where(
                (base_data == 3000)
                & (data['bettre'] >= 3) & (data['picgla'] >= 3) & (data['picratio'] >= 60)
                & (data['bettre'] >= data['poptre']) & (data['bettre'] >= data['populbt']),
                119, base_data)

            #### KEY BOREAL BROADLEAF TYPES
            ####____________________________________________________

            # 213. Birch (-White Spruce) Active Floodplain
            base_data = np.where(
                (base_data == 2000) & (data['surficial'] == 8)
                & (data['bettre'] >= 3) & (data['poptre'] < 10)
                & (data['populbt'] < (data['bettre'] * 0.8)) & (data['bettre'] >= data['poptre']),
                213, base_data)

            # 214. Poplar (-White Spruce) Active Floodplain
            base_data = np.where(
                (base_data == 2000) & (data['surficial'] == 8)
                & (data['populbt'] >= 3)
                & (data['populbt'] >= (data['bettre'] * 0.8))
                & (data['populbt'] >= data['poptre']) & (data['poptre'] < 10),
                214, base_data)

            # 161. Alaska-Yukon Aspen Dry Woodland / Steppe Bluff
            base_data = np.where(
                (base_data == 2000) & (data['fire'] < 1990)
                & (data['poptre'] >= 3) & (data['slope'] >= 12) & (data['aspect'] >= 300)
                & (data['bettre'] < data['poptre']) & (data['populbt'] < data['poptre']),
                161, base_data)

            # 162. Alaska-Yukon Aspen Forest Mesic (Successional)
            base_data = np.where(
                (base_data == 2000) & (data['fire'] < 1990)
                & (data['poptre'] >= 3) & ((data['slope'] < 12) | (data['aspect'] < 300))
                & (data['bettre'] < data['poptre']) & (data['populbt'] < data['poptre']),
                162, base_data)

            # 163. Alaska-Yukon Post-burn Aspen Forest Mesic
            base_data = np.where(
                (base_data == 2000) & (data['fire'] >= 1990) & (data['poptre'] >= 3)
                & (data['bettre'] < data['poptre']) & (data['populbt'] < data['poptre']),
                163, base_data)

            # 153. Alaska-Yukon Poplar Woodland Mesic
            base_data = np.where(
                (base_data == 2000) & (data['populbt'] >= 3)
                & (data['populbt'] >= data['poptre']) & (data['bettre'] < data['populbt']),
                153, base_data)

            # 111. Alaska-Yukon Birch Forest Mesic (Central)
            base_data = np.where(
                (base_data == 2000) & (data['fire'] < 1990) & (data['bettre'] >= 3)
                & (data['bettre'] >= data['populbt']) & (data['bettre'] >= data['poptre']),
                111, base_data)

            # 116. Alaska-Yukon Post-burn Recovering Birch Forest Mesic (Central)
            base_data = np.where(
                (base_data == 2000) & (data['fire'] >= 1990) & (data['bettre'] >= 3)
                & (data['bettre'] >= data['populbt']) & (data['bettre'] >= data['poptre']),
                116, base_data)

            #### KEY BOREAL TUSSOCK TYPES
            ####____________________________________________________

            # 205. Alaska-Yukon Tussock Peatland, Ombrotrophic
            base_data = np.where(
                (base_data == 4000) & ((data['sphagn'] >= 20) | (data['peat'] >= 38)),
                205, base_data)

            # 294. Arctic Ericaceous (-Birch) Lichen Tundra
            base_data = np.where(
                (base_data == 4000) & (data['surficial'] != 2)
                & (((data['lichen'] >= 35) & (data['fire'] < 1980))
                   | ((data['lichen'] >= 45) & (data['fire'] < 2019))),
                294, base_data)

            # 272. Arctic Tussock Dwarf Shrub Tundra
            base_data = np.where(
                (base_data == 4000) & (data['ndshrub'] < 15),
                272, base_data)

            # 274. Arctic Tussock Low Shrub Tundra
            base_data = np.where(
                (base_data == 4000) & (data['ndshrub'] >= 15),
                274, base_data)

            #### KEY BOREAL SHRUB TYPES
            ####____________________________________________________

            # 294. Arctic Ericaceous (-Birch) Lichen Tundra
            base_data = np.where(
                (base_data == 5001) & (data['surficial'] != 2)
                & (((data['lichen'] >= 35) & (data['fire'] < 1980))
                   | ((data['lichen'] >= 45) & (data['fire'] < 2019))),
                294, base_data)

            # 173. Alaska-Yukon Dwarf Shrub-Lichen
            base_data = np.where(
                (base_data == 5001) & (data['surficial'] == 2)
                & (data['ndshrub'] < 15) & (data['lichen'] >= 35),
                173, base_data)

            # 185. Alaska-Yukon Post-burn Birch-Willow Mesic
            base_data = np.where(
                (base_data == 5001) & (data['fire'] >= 1990)
                & ((data['ndsalix'] + data['betshr']) >= 5),
                185, base_data)

            # 244. Alaska-Yukon Post-Burn Recovering Birch-Willow Wet
            base_data = np.where(
                (base_data == 5002) & (data['fire'] >= 1990)
                & ((data['ndsalix'] + data['betshr']) >= 5),
                244, base_data)

            # 221. Alaska-Yukon Alder-Willow Active Floodplain
            base_data = np.where(
                (np.isin(base_data, [5001, 5002])) & (data['surficial'] == 8)
                & (data['ndshrub'] >= 15) & (data['alnus'] >= 5)
                & (data['alnus'] >= (data['ndsalix'] * 0.5)),
                221, base_data)

            # 222. Alaska-Yukon Willow Active Floodplain
            base_data = np.where(
                (np.isin(base_data, [5001, 5002])) & (data['surficial'] == 8)
                & (data['ndshrub'] >= 15) & (data['ndsalix'] >= 5)
                & (data['alnus'] < (data['ndsalix'] * 0.5)),
                222, base_data)

            # 172. Alaska-Yukon Dryas-Willow Dwarf Shrub
            base_data = np.where(
                (base_data == 5001)
                & (data['ndshrub'] < 15) & ((data['dryas'] >= 3) | (data['dsalix'] >= 3))
                & ((data['eridwarf'] < data['dsalix']) | (data['eridwarf'] < (data['dryas'] * 0.5))),
                172, base_data)

            # 171. Alaska-Yukon Dryas-Ericaceous Dwarf Shrub
            base_data = np.where(
                (base_data == 5001)
                & (data['ndshrub'] < 15) & (data['dryas'] >= 3) & (data['eridwarf'] >= 3)
                & (data['eridwarf'] >= data['dsalix']) & (data['dryas'] >= (data['eridwarf'] * 0.5)),
                171, base_data)

            # 174. Alaska-Yukon Ericaceous Dwarf Shrub
            base_data = np.where(
                (base_data == 5001)
                & (data['ndshrub'] < 15) & ((data['dryas'] >= 3) | (data['eridwarf'] >= 3))
                & (data['eridwarf'] >= data['dsalix']) & (data['dryas'] < (data['eridwarf'] * 0.5)),
                174, base_data)

            # 181. Alaska-Yukon Alder Mesic
            base_data = np.where(
                (base_data == 5001)
                & (data['ndshrub'] >= 15) & (data['alnus'] >= 5)
                & (data['alnus'] >= (data['ndsalix'] * 1.5)),
                181, base_data)

            # 182. Alaska-Yukon Alder-Willow Mesic
            base_data = np.where(
                (base_data == 5001)
                & (data['ndshrub'] >= 15) & (data['alnus'] >= 5)
                & (data['alnus'] < (data['ndsalix'] * 1.5)) & (data['alnus'] >= (data['ndsalix'] * 0.5)),
                182, base_data)

            # 186. Alaska-Yukon Willow Mesic
            base_data = np.where(
                (base_data == 5001)
                & (data['ndshrub'] >= 15) & (data['ndsalix'] >= 5)
                & (data['alnus'] < (data['ndsalix'] * 0.5)) & (data['ndsalix'] >= (data['betshr'] * 1.5)),
                186, base_data)

            # 184. Alaska-Yukon Birch-Willow Mesic
            base_data = np.where(
                (base_data == 5001)
                & (data['ndshrub'] >= 15) & (data['betshr'] >= 5)
                & (data['ndsalix'] >= (data['erishrub'] * 0.8)) & (data['ndsalix'] < (data['betshr'] * 1.5)),
                184, base_data)

            # 183. Alaska-Yukon Ericaceous (-Birch) Mesic
            base_data = np.where(
                (base_data == 5001)
                & (data['ndshrub'] >= 15) & (data['erishrub'] >= 5)
                & (data['ndsalix'] < (data['erishrub'] * 0.8)),
                183, base_data)

            # 243. Alaska-Yukon Alder-Willow Wet
            base_data = np.where(
                (base_data == 5002)
                & (data['ndshrub'] >= 15) & (data['alnus'] >= 5)
                & (data['alnus'] >= (data['ndsalix'] * 0.5)),
                243, base_data)

            # 242. Alaska-Yukon Willow Wet
            base_data = np.where(
                (base_data == 5002)
                & (data['ndshrub'] >= 15) & (data['ndsalix'] >= 5)
                & (data['alnus'] < (data['ndsalix'] * 0.5)) & (data['ndsalix'] >= (data['betshr'] * 1.5)),
                242, base_data)

            # 241. Alaska-Yukon Birch-Willow Wet
            base_data = np.where(
                (base_data == 5002)
                & (data['ndshrub'] >= 15) & (data['betshr'] >= 5)
                & (data['ndsalix'] < (data['betshr'] * 1.5)),
                241, base_data)

            # 204. Alaska-Yukon Shrub-Sphagnum Peatland, Ombrotrophic
            base_data = np.where(
                (base_data == 5003)
                & (data['sphagn'] >= 15) & (data['ndshrub'] >= 15) & (data['erivag'] < 15),
                204, base_data)

            # 201. Alaska-Yukon (Dwarf Shrub) Sedge-Sphagnum Peatland, Ombrotrophic
            base_data = np.where(
                (base_data == 5003)
                & (data['sphagn'] >= 15) & (data['ndshrub'] < 15) & (data['erivag'] < 15),
                201, base_data)

            # 205. Alaska-Yukon Tussock Peatland, Ombrotrophic
            base_data = np.where(
                (base_data == 5003) & (data['erivag'] >= 15),
                205, base_data)

            # 207. Alaska-Yukon Shrub-Sedge Peatland, Minerotrophic
            base_data = np.where(
                (base_data == 5003) & (data['sphagn'] < 15) & (data['erivag'] < 15),
                207, base_data)

            #### KEY BOREAL HERBACEOUS TYPES
            ####____________________________________________________

            # 294. Arctic Ericaceous (-Birch) Lichen Tundra
            base_data = np.where(
                (base_data == 6001) & (data['surficial'] != 2)
                & (((data['lichen'] >= 35) & (data['fire'] < 1980))
                   | ((data['lichen'] >= 45) & (data['fire'] < 2019))),
                294, base_data)

            # 175. Alaska-Yukon Alpine Meadow Mesic
            base_data = np.where(
                (base_data == 6001) & (data['surficial'] == 2),
                175, base_data)

            # 223. Alaska-Yukon Herbaceous Active Floodplain
            base_data = np.where(
                (base_data == 6001) & (data['surficial'] == 8),
                223, base_data)

            # 191. Alaska-Yukon Calamagrostis-Forb Meadow Mesic
            base_data = np.where(
                (base_data == 6001) & (data['mwcalama'] >= 15),
                191, base_data)

            # 192. Alaska-Yukon Forb-Graminoid Meadow Mesic Acidic
            base_data = np.where(
                (base_data == 6001) & (data['mwcalama'] < 15),
                192, base_data)

            # 226. Alaska-Yukon Sedge-Calamagrostis Wet Meadow (Mineral/Riverine)
            base_data = np.where(
                (base_data == 6002) & (data['mwcalama'] >= 20),
                226, base_data)

            # 225. Alaska-Yukon Sedge Wet Meadow (Mineral/Riverine)
            base_data = np.where(
                (base_data == 6002) & (data['mwcalama'] < 20) & (data['wetsed'] >= 15),
                225, base_data)

            # 227. Alaska-Yukon Forb-Graminoid Meadow Wet (Mineral/Riverine)
            base_data = np.where(
                (base_data == 6002) & (data['mwcalama'] < 20) & (data['wetsed'] < 15),
                227, base_data)

            # 201. Alaska-Yukon (Dwarf Shrub) Sedge-Sphagnum Peatland, Ombrotrophic
            base_data = np.where(
                (base_data == 6003) & (data['sphagn'] >= 15),
                201, base_data)

            # 206. Alaska-Yukon Sedge Peatland, Minerotrophic
            base_data = np.where(
                (base_data == 6003) & (data['sphagn'] < 15),
                206, base_data)

            #### POST-PROCESSING
            ####____________________________________________________

            # Create post-processing mask
            omitted_mask = np.isin(type_data, [995, 996, 998, 176, 224, 250])
            target_mask = ~(omitted_mask | (type_data == nodata_value))

            # Isolate target data
            isolated_data = np.where(target_mask, type_data, nodata_value)

            # Apply incremental sieve
            print('\tApplying size threshold...')
            sieve_data = features.sieve(isolated_data.astype('int16'), size=50, connectivity=4)

            # Fill no data using a categorical nibble
            print('\tFilling no data...')
            sieve_data = np.where(
                (sieve_data == 0) | (sieve_data == 990) | (sieve_data >= 1000),
                nodata_value, sieve_data)
            nibble_data = categorical_nibble(sieve_data, nodata_value)

            # Generalize the raster shapes with majority filter
            print('\tApplying majority filter...')
            filter_data = apply_smoothing_filter(nibble_data, window_size=3, iterations=2)

            # Apply sieve
            print('\tApplying size threshold...')
            sieve_data = features.sieve(filter_data.astype('int16'), size=50, connectivity=4)
            sieve_data = features.sieve(sieve_data.astype('int16'), size=100, connectivity=4)
            sieve_data = features.sieve(sieve_data.astype('int16'), size=100, connectivity=4)

            # Add omitted data into final raster
            print('\tAdding omitted data...')
            combine_data = np.where(omitted_mask, type_data, sieve_data)

            # Generalize the raster shapes with majority filter
            print('\tApplying majority filter...')
            filter_data = apply_smoothing_filter(combine_data, window_size=3, iterations=1)

            # Extract to study area
            print('\tExtracting to study area...')
            export_data = np.where(data['area'] == 1, filter_data, nodata_value)

            # Crop the export data to the export extent
            export_data = export_data[
                row_offset: row_offset + dst_height,
                col_offset: col_offset + dst_width
            ]

            # Write results
            dst.write(export_data.astype('int16'), 1)

            # Upload and Clean Up
        print('Uploading raster dataset to Google Cloud Storage...')
        upload_to_gcs(type_output, gcs_output, storage_client)
        os.remove(type_output)
        end_timing(start_time)
    else:
        print(f'{grid} already exists.')

    # Increase count
    grid_count += 1

# Close all raster connections
for src in raster_sources.values():
    src.close()

#### PROCESS CLOUD-OPTIMIZED GEOTIFF
####____________________________________________________

# Create merged VRT raster
input_files = glob.glob(os.path.join(tiles_folder, '*.tif'))

# Merge raster tiles
print(f'Merging {len(input_files)} tiles...')
start_time = time.time()
vrt_data = gdal.BuildVRT(
    vrt_intermediate,
    input_files,
    outputSRS='EPSG:3338',
    xRes=2,
    yRes=2,
    VRTNodata=nodata_value,
    outputBounds=area_bounds)
vrt_data = None

# Set translation options for GDAL COG driver
cog_options = gdal.TranslateOptions(
    format='COG',
    creationOptions=[
        'COMPRESS=DEFLATE',
        'PREDICTOR=NO',
        'BLOCKSIZE=512',
        'NUM_THREADS=ALL_CPUS',
        'BIGTIFF=YES',
        'RESAMPLING=NEAREST',
        'OVERVIEW_RESAMPLING=NEAREST'
    ]
)

# Translate raster to cloud-optimized geotiff
print('Converting raster to cloud-optimized geotiff...')
cog_data = gdal.Translate(surficial_output, vrt_intermediate, options=cog_options)
cog_data = None
end_timing(start_time)