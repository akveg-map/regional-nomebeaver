# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Parse vegetation types
# Author: Timm Nawrocki
# Last Updated: 2026-10-21
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Parse vegetation types" runs a programmatic key to the AKVEG map classes using foliar cover and surficial features maps, as well as additional ancillary data.
# ---------------------------------------------------------------------------

# Set execution parameters
processors = 1
processor = 1
nodata_value = -32768

# Import packages
import os
import glob
import time
import math
import collections
import dbf
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio import features
from osgeo import gdal
from google.cloud import storage
from akutils import *

# Configure GDAL
gdal.UseExceptions()

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Define final GCS path for the output
output_name = 'types_800mmu_2m_3338.tif'
final_gcs_output = f'{gcs_base}/veg_types/{output_name}'

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
region_folder = os.path.join(project_folder, 'data_input/region_data')
region_geopackage = os.path.join(region_folder, 'region_data_3338.gpkg')
covariate_folder = os.path.join(project_folder, 'data_input/covariate_data')
chm_folder = os.path.join(project_folder, 'data_input/canopy_height')
surficial_folder = os.path.join(project_folder, 'data_output/surficial_data')
output_folder = os.path.join(project_folder, 'data_output/veg_types')
tiles_folder = os.path.join(output_folder, 'tiles')
schema_folder = os.path.join(drive, root_folder, 'Repositories/class-descriptions')

# Define input files
area_input = os.path.join(region_folder, 'nomebeaver_domain_2m_3338.tif')
grid_layer = 'tiles_001_3338'
covariate_input = os.path.join(covariate_folder, 'covariates_zonal_2m_3338.tif')
chm_input = os.path.join(chm_folder, 'chm_segments_2m_3338_v20261020.tif')
foliar_input = os.path.join(covariate_folder, 'foliar_zonal_2m_3338.tif')
peat_input = os.path.join(covariate_folder, 'peat_probability_2m_3338.tif')
fire_input = os.path.join(covariate_folder, 'fire_year_2m_3338.tif')
burned_input = os.path.join(covariate_folder, 'recently_burned_2m_3338.tif')
surficial_input = os.path.join(surficial_folder, 'surficial_2m_3338.tif')
schema_input = os.path.join(schema_folder, 'AKVEG_MapClass_Schema.csv')

# Define intermediate files
vrt_intermediate = os.path.join(output_folder, 'types_inter_2m_3338.vrt')

# Define output files
type_output = os.path.join(output_folder, output_name)

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
zonal_topo = ['elevation', 'aspect', 'slope']
zonal_foliar = ['alnus', 'betshr', 'bettre', 'brotre', 'dryas', 'dsalix',
                    'empnig', 'erivag', 'feather', 'forb', 'gramin',
                    'lichen', 'mwcalama', 'ndsalix', 'neetre', 'nerishr',
                    'picgla', 'picmar', 'poptre', 'populbt', 'rhoshr',
                    'sphagn', 'vaculi', 'vacvit', 'wetforb', 'wetsed']
zonal_dist = ['bromos', 'wetgram']
zonal_sum = ['eridwarf', 'erishrub', 'herbac', 'ndshrub', 'shrub', 'trees', 'wetind']
zonal_ratio = ['deciduous_ratio', 'picea_ratio', 'tussock_ratio']
zonal_chm = ['chm_rh90_cm']

# Concatenate zonal_statistics sets
zonal_all = zonal_foliar + zonal_dist + zonal_sum + zonal_ratio

# Identify band indices for covariate input raster
with rasterio.open(covariate_input) as src:
    topo_band_map = {desc: idx for idx, desc in enumerate(src.descriptions, start=1) if desc}
    try:
        topo_band_dict = {name: topo_band_map[name] for name in zonal_topo}
    except KeyError as e:
        raise KeyError(f'Requested zonal band {e} was not found in raster band descriptions.')

# Identify band indices for foliar input raster
with rasterio.open(foliar_input) as src:
    foliar_band_map = {desc: idx for idx, desc in enumerate(src.descriptions, start=1) if desc}
    try:
        foliar_band_dict = {name: foliar_band_map[name] for name in zonal_all}
    except KeyError as e:
        raise KeyError(f'Requested zonal band {e} was not found in raster band descriptions.')

# Identify band indices for canopy height input raster
with rasterio.open(chm_input) as src:
    chm_band_map = {desc: idx for idx, desc in enumerate(src.descriptions, start=1) if desc}
    try:
        chm_band_dict = {name: chm_band_map[name] for name in zonal_chm}
    except KeyError as e:
        raise KeyError(f'Requested zonal band {e} was not found in raster band descriptions.')

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

# Open dataset connections for input rasters
raster_sources = {name: rasterio.open(path) for name, path in raster_paths.items()}
topo_source = rasterio.open(covariate_input)
foliar_source = rasterio.open(foliar_input)
chm_source = rasterio.open(chm_input)

# Read spatial transform and cell dimensions from area_input
area_transform = raster_sources['area'].transform
align_x = area_transform[2]
align_y = area_transform[5]
res_x = area_transform[0]
res_y = abs(area_transform[4])

# Read bounding bounds from domain raster
area_bounds = raster_bounds(area_input)

# Post-process each grid in grid list
grid_count = 1
for index, row in grid_data.iterrows():
    # Define grid code
    grid = row['grid_code']

    # Define output paths
    veg_tile = os.path.join(tiles_folder, f'{grid}_2m_3338.tif')

    # Create output raster if it does not already exist in GCS
    if not os.path.exists(veg_tile):
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
            'dtype': 'int16',
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
            # Build data dictionary for covariates
            data = {name: read_raster_block(src, window_processing) for name, src in raster_sources.items()}

            # Populate data dictionary with topographic bands
            for var_name, band_idx in topo_band_dict.items():
                data[var_name] = read_raster_block(topo_source, window_processing, band_idx)

            # Populate data dictionary with foliar bands
            for var_name, band_idx in foliar_band_dict.items():
                data[var_name] = read_raster_block(foliar_source, window_processing, band_idx)

            # Populate data dictionary with chm bands
            for var_name, band_idx in chm_band_dict.items():
                data[var_name] = read_raster_block(chm_source, window_processing, band_idx)

            # Map aliases expected by programmatic key
            data['decratio'] = data['deciduous_ratio']
            data['tussock'] = data['tussock_ratio']
            data['picratio'] = data['picea_ratio']
            data['chm'] = data['chm_rh90_cm']

            # Initialize base classification array
            type_data = np.zeros_like(data['area'], dtype=np.int16)

            #### KEY THE LAND COVER TYPES
            ####____________________________________________________

            # 1000. needleleaf trees
            type_data = np.where(
                (type_data == 0) & (data['decratio'] < 40)
                & (((data['neetre'] >= 8) & (~np.isin(data['surficial'], [1, 2]))
                    & (data['fire'] < 1980))
                   | ((data['neetre'] >= 12) & (~np.isin(data['surficial'], [1, 2]))
                      & (data['fire'] >= 1980))
                   | ((data['neetre'] >= 5) & (data['chm'] >= 500))),
                1000, type_data)

            # 2000. broadleaf trees
            type_data = np.where(
                (type_data == 0) & (data['decratio'] >= 70) & (data['brotre'] >= (data['ndshrub'] * 0.5))
                & (((data['brotre'] >= 8) & (~np.isin(data['surficial'], [1, 2]))
                    & (data['fire'] < 1980))
                   | ((data['brotre'] >= 12) & (~np.isin(data['surficial'], [1, 2]))
                      & (data['fire'] >= 1980))
                   | ((data['brotre'] >= 5) & (data['chm'] >= 500))),
                2000, type_data)

            # 3000. mixed trees
            type_data = np.where(
                (type_data == 0) & ((data['decratio'] >= 40) & (data['decratio'] < 70))
                & (data['trees'] >= (data['ndshrub'] * 0.5))
                & (((data['trees'] >= 8) & (~np.isin(data['surficial'], [1, 2]))
                    & (data['fire'] < 1980))
                   | ((data['trees'] >= 12) & (~np.isin(data['surficial'], [1, 2]))
                      & (data['fire'] >= 1980))
                   | ((data['trees'] >= 5) & (data['chm'] >= 500))),
                3000, type_data)

            # 4000. tussock
            type_data = np.where(
                (type_data == 0)
                & ((data['erivag'] >= 20)
                   | ((data['erivag'] >= 10) & (data['ndshrub'] < 40))
                   | ((data['erivag'] >= 8) & (data['ndshrub'] < 25) & (data['tussock'] >= 30))),
                4000, type_data)

            # 5000. shrub
            type_data = np.where(
                (type_data == 0)
                & ((data['shrub'] >= 20)
                   | ((data['shrub'] >= 12) & (data['fire'] >= 1980))),
                5000, type_data)

            # 6000. herbaceous
            type_data = np.where(
                (type_data == 0)
                & ((data['herbac'] >= 8) | (data['sphagn'] >= 8) | (data['peat'] >= 38)),
                6000, type_data)

            # 995. ORV trail/disturbance
            type_data = np.where(
                data['surficial'] == 6,
                995, type_data)

            # 996. infrastructure
            type_data = np.where(
                data['surficial'] == 7,
                996, type_data)

            # 998. water
            type_data = np.where(
                data['surficial'] == 5,
                998, type_data)

            # 176. Alaska-Yukon Alpine Barren & Sparsely Vegetated
            type_data = np.where(
                data['surficial'] == 1,
                176, type_data)

            # 224. Alaska-Yukon Barren & Sparsely Vegetated Active Floodplain
            type_data = np.where(
                data['surficial'] == 9,
                224, type_data)

            # 250. Alaska-Yukon Barren & Sparsely Vegetated
            type_data = np.where(
                data['surficial'] == 4,
                250, type_data)

            #### KEY THE FRESHWATER MARSH TYPES
            ####____________________________________________________

            # 228. Alaska-Yukon Freshwater Marsh
            type_data = np.where(
                (type_data == 6000)
                & (data['wetgram'] >= 45) & (data['mwcalama'] < 10)
                & (data['sphagn'] < 8) & (data['bromos'] < 50),
                228, type_data)

            #### KEY MOISTURE REGIMES
            ####____________________________________________________

            # Define moisture regime masks
            wet_mask = (
                    (data['wetind'] >= 15) | (data['wetsed'] >= 10)
                    | (data['wetforb'] >= 20) | (data['wetgram'] >= 50)
            )
            peat_mask = (
                    (((data['sphagn'] >= 20) | (data['peat'] >= 50)) & (data['fire'] < 1984))
                    | (((data['sphagn'] >= 30) | (data['peat'] >= 50)) & (data['fire'] >= 1984))
            )

            # 1001. Needleleaf Mesic
            type_data = np.where(
                (type_data == 1000)
                & (data['erivag'] < 12) & ~wet_mask,
                1001, type_data)

            # 1002. Needleleaf Wet
            type_data = np.where(
                (type_data == 1000)
                & ((data['erivag'] >= 12) | wet_mask),
                1002, type_data)

            # 5001. Shrub Mesic
            type_data = np.where(
                (type_data == 5000) & ~wet_mask & ~peat_mask,
                5001, type_data)

            # 5002. Shrub Wet
            type_data = np.where(
                (type_data == 5000) & wet_mask & ~peat_mask,
                5002, type_data)

            # 5003. Shrub Peat
            type_data = np.where(
                (type_data == 5000) & peat_mask,
                5003, type_data)

            # 6001. Herbaceous Mesic
            type_data = np.where(
                (type_data == 6000) & ~wet_mask & ~peat_mask,
                6001, type_data)

            # 6002. Herbaceous Wet
            type_data = np.where(
                (type_data == 6000) & wet_mask & ~peat_mask,
                6002, type_data)

            # 6003. Herbaceous Peat
            type_data = np.where(
                (type_data == 6000) & peat_mask,
                6003, type_data)

            #### KEY BOREAL MESIC NEEDLELEAF TYPES
            ####____________________________________________________

            # 212. Alaska-Yukon White Spruce Active Floodplain
            type_data = np.where(
                (np.isin(type_data, [1001, 1002])) & (data['surficial'] == 8)
                & (data['picgla'] >= 5) & (data['picratio'] >= 40),
                212, type_data)

            # 154. Alaska-Yukon Spruce-Lichen Woodland Mesic
            type_data = np.where(
                (type_data == 1001)
                & (data['lichen'] >= 35) & ((data['picgla'] >= 3) | (data['picmar'] >= 3)),
                154, type_data)

            # 155. Alaska-Yukon White Spruce Woodland Mesic
            type_data = np.where(
                (type_data == 1001)
                & (data['trees'] < 20) & (data['picratio'] >= 60),
                155, type_data)

            # 151. Alaska-Yukon Black Spruce Woodland Mesic
            type_data = np.where(
                (type_data == 1001)
                & (data['trees'] < 20) & (data['picratio'] < 40),
                151, type_data)

            # 152. Alaska-Yukon Mixed Spruce Woodland Mesic
            type_data = np.where(
                (type_data == 1001)
                & (data['trees'] < 20) & (data['picratio'] >= 40) & (data['picratio'] < 60),
                152, type_data)

            # 117. Alaska-Yukon White Spruce Forest Mesic (Central)
            type_data = np.where(
                (type_data == 1001)
                & (data['picgla'] >= 3) & (data['trees'] >= 20) & (data['picratio'] >= 60),
                117, type_data)

            # 112. Alaska-Yukon Black Spruce Forest Mesic (Central)
            type_data = np.where(
                (type_data == 1001)
                & (data['picmar'] >= 3) & (data['trees'] >= 20) & (data['picratio'] < 40),
                112, type_data)

            # 114. Alaska-Yukon Mixed Spruce Forest Mesic (Central)
            type_data = np.where(
                (type_data == 1001)
                & (data['picmar'] >= 3) & (data['picgla'] >= 3) & (data['trees'] >= 20)
                & (data['picratio'] >= 40) & (data['picratio'] < 60),
                114, type_data)

            # Correct woodlands in burned areas
            type_data = np.where((np.isin(type_data, [151, 152, 155])) & (data['fire'] >= 1984)
                                 & (data['chm'] < 50),
                                 5001, type_data)

            # Correct spruce forest in burned areas
            type_data = np.where((np.isin(type_data, [112, 114, 117])) & (data['fire'] >= 1984)
                                 & (data['chm'] < 50) & (data['neetre'] < 20),
                                 5001, type_data)

            #### KEY BOREAL WET NEEDLELEAF TYPES
            ####____________________________________________________

            # 203. Alaska-Yukon Black Spruce-Tussock Peatland, Ombrotrophic
            type_data = np.where(
                (type_data == 1002)
                & (data['picmar'] >= 3) & (data['picratio'] < 60)
                & (data['erivag'] >= 8) & (data['chm'] < 500),
                203, type_data)

            # 202. Alaska-Yukon Black Spruce Peatland, Ombrotrophic
            type_data = np.where(
                (type_data == 1002)
                & (data['picmar'] >= 3) & (data['picratio'] < 60) & (data['chm'] < 500)
                & ((data['sphagn'] >= 25) | (data['wetsed'] >= 10) | (data['peat'] >= 50)),
                202, type_data)

            # 211. Alaska-Yukon Black Spruce Forest Wet
            type_data = np.where((type_data == 1002), 211, type_data)

            # Correct black spruce wet in burned areas
            type_data = np.where((type_data == 211) & (data['fire'] >= 1984)
                                 & (data['chm'] < 50),
                                 5002, type_data)

            #### KEY BOREAL MIXED FOREST TYPES
            ####____________________________________________________

            # 213. Birch (-White Spruce) Active Floodplain
            type_data = np.where(
                (type_data == 3000) & (data['surficial'] == 8)
                & (data['bettre'] >= 3)
                & (data['populbt'] < (data['bettre'] * 0.8)) & (data['bettre'] >= data['poptre']),
                213, type_data)

            # 214. Poplar (-White Spruce) Active Floodplain
            type_data = np.where(
                (type_data == 3000) & (data['surficial'] == 8)
                & (data['populbt'] >= 3)
                & (data['populbt'] >= (data['bettre'] * 0.8)) & (data['populbt'] >= data['poptre']),
                214, type_data)

            # 163. Alaska-Yukon Post-burn Recovering Aspen Forest Mesic
            type_data = np.where(
                (type_data == 3000) & (data['fire'] >= 1984)
                & (data['poptre'] >= 3)
                & (data['bettre'] < data['poptre']) & (data['populbt'] < data['poptre']),
                163, type_data)

            # 116. Alaska-Yukon Post-burn Recovering Birch Forest Mesic (Central)
            type_data = np.where(
                (type_data == 3000) & (data['fire'] >= 1984)
                & (data['bettre'] >= 3)
                & (data['bettre'] >= data['populbt']) & (data['bettre'] >= data['poptre']),
                116, type_data)

            # 113. Alaska-Yukon Black Spruce-Deciduous Forest Mesic (Central)
            type_data = np.where(
                (type_data == 3000)
                & (data['brotre'] >= 3) & (data['picmar'] >= 3) & (data['picratio'] < 40),
                113, type_data)

            # 115. Alaska-Yukon Mixed Spruce-Deciduous Forest Mesic (Central)
            type_data = np.where(
                (type_data == 3000)
                & (data['brotre'] >= 3) & (data['picmar'] >= 3) & (data['picgla'] >= 3)
                & (data['picratio'] >= 40) & (data['picratio'] < 60),
                115, type_data)

            # 118. Alaska-Yukon White Spruce-Aspen Forest Mesic (Central)
            type_data = np.where(
                (type_data == 3000)
                & (data['poptre'] >= 3) & (data['picgla'] >= 3) & (data['picratio'] >= 60)
                & (data['bettre'] < data['poptre']) & (data['populbt'] < data['poptre']),
                118, type_data)

            # 120. Alaska-Yukon White Spruce-Poplar Forest Mesic (Central)
            type_data = np.where(
                (type_data == 3000)
                & (data['populbt'] >= 3) & (data['picgla'] >= 3) & (data['picratio'] >= 60)
                & (data['populbt'] >= data['poptre']) & (data['bettre'] < data['populbt']),
                120, type_data)

            # 119. Alaska-Yukon White Spruce-Birch Forest Mesic (Central)
            type_data = np.where(
                (type_data == 3000)
                & (data['bettre'] >= 3) & (data['picgla'] >= 3) & (data['picratio'] >= 60)
                & (data['bettre'] >= data['poptre']) & (data['bettre'] >= data['populbt']),
                119, type_data)

            #### KEY BOREAL BROADLEAF TYPES
            ####____________________________________________________

            # 213. Birch (-White Spruce) Active Floodplain
            type_data = np.where(
                (type_data == 2000) & (data['surficial'] == 8)
                & (data['bettre'] >= 3) & (data['poptre'] < 10)
                & (data['populbt'] < (data['bettre'] * 0.8)) & (data['bettre'] >= data['poptre']),
                213, type_data)

            # 214. Poplar (-White Spruce) Active Floodplain
            type_data = np.where(
                (type_data == 2000) & (data['surficial'] == 8)
                & (data['populbt'] >= 3)
                & (data['populbt'] >= (data['bettre'] * 0.8))
                & (data['populbt'] >= data['poptre']) & (data['poptre'] < 10),
                214, type_data)

            # 161. Alaska-Yukon Aspen Dry Woodland / Steppe Bluff
            type_data = np.where(
                (type_data == 2000) & (data['fire'] < 1984)
                & (data['poptre'] >= 3) & (data['slope'] >= 12) & (data['aspect'] >= 300)
                & (data['bettre'] < data['poptre']) & (data['populbt'] < data['poptre']),
                161, type_data)

            # 162. Alaska-Yukon Aspen Forest Mesic (Successional)
            type_data = np.where(
                (type_data == 2000) & (data['fire'] < 1984)
                & (data['poptre'] >= 3) & ((data['slope'] < 12) | (data['aspect'] < 300))
                & (data['bettre'] < data['poptre']) & (data['populbt'] < data['poptre']),
                162, type_data)

            # 163. Alaska-Yukon Post-burn Aspen Forest Mesic
            type_data = np.where(
                (type_data == 2000) & (data['fire'] >= 1984)
                & (data['poptre'] >= 3)
                & (data['bettre'] < data['poptre']) & (data['populbt'] < data['poptre']),
                163, type_data)

            # 153. Alaska-Yukon Poplar Woodland Mesic
            type_data = np.where(
                (type_data == 2000)
                & (data['populbt'] >= 3)
                & (data['populbt'] >= data['poptre']) & (data['bettre'] < data['populbt']),
                153, type_data)

            # 111. Alaska-Yukon Birch Forest Mesic (Central)
            type_data = np.where(
                (type_data == 2000) & (data['fire'] < 1984)
                & (data['bettre'] >= 3)
                & (data['bettre'] >= data['populbt']) & (data['bettre'] >= data['poptre']),
                111, type_data)

            # 116. Alaska-Yukon Post-burn Recovering Birch Forest Mesic (Central)
            type_data = np.where(
                (type_data == 2000) & (data['fire'] >= 1984)
                & (data['bettre'] >= 3)
                & (data['bettre'] >= data['populbt']) & (data['bettre'] >= data['poptre']),
                116, type_data)

            #### KEY BOREAL TUSSOCK TYPES
            ####____________________________________________________

            # 203. Alaska-Yukon Black Spruce-Tussock Peatland, Ombrotrophic
            type_data = np.where(
                (type_data == 4000)
                & (((data['neetre'] >= 5) & (data['fire'] < 1984)) |
                   ((data['neetre'] >= 8) & (data['fire'] >= 1984))),
                203, type_data)

            # 205. Alaska-Yukon Tussock Peatland, Ombrotrophic
            type_data = np.where(
                (type_data == 4000) & ((data['sphagn'] >= 20) | (data['peat'] >= 38)),
                205, type_data)

            # 294. Arctic Ericaceous (-Birch) Lichen Tundra
            type_data = np.where(
                (type_data == 4000) & (data['surficial'] != 2)
                & (((data['lichen'] >= 35) & (data['fire'] < 1980))
                   | ((data['lichen'] >= 45) & (data['fire'] < 2019))),
                294, type_data)

            # 272. Arctic Tussock Dwarf Shrub Tundra
            type_data = np.where(
                (type_data == 4000) & (data['ndshrub'] < 15),
                272, type_data)

            # 274. Arctic Tussock Low Shrub Tundra
            type_data = np.where(
                (type_data == 4000) & (data['ndshrub'] >= 15),
                274, type_data)

            #### KEY BOREAL SHRUB TYPES
            ####____________________________________________________

            # 294. Arctic Ericaceous (-Birch) Lichen Tundra
            type_data = np.where(
                (type_data == 5001) & (data['surficial'] != 2)
                & (((data['lichen'] >= 35) & (data['fire'] < 1980))
                   | ((data['lichen'] >= 45) & (data['fire'] < 2019))),
                294, type_data)

            # 173. Alaska-Yukon Dwarf Shrub-Lichen
            type_data = np.where(
                (type_data == 5001) & (data['surficial'] == 2)
                & (data['ndshrub'] < 15) & (data['lichen'] >= 35),
                173, type_data)

            # 172. Alaska-Yukon Dryas-Willow Dwarf Shrub
            type_data = np.where(
                (type_data == 5001)
                & ((data['ndshrub'] < 5) | (data['surficial'] == 2))
                & ((data['dryas'] >= 3) | (data['dsalix'] >= 3))
                & ((data['eridwarf'] < data['dsalix']) | (data['eridwarf'] < (data['dryas'] * 0.5))),
                172, type_data)

            # 171. Alaska-Yukon Dryas-Ericaceous Dwarf Shrub
            type_data = np.where(
                (type_data == 5001)
                & ((data['ndshrub'] < 5) | (data['surficial'] == 2))
                & (data['dryas'] >= 3) & (data['eridwarf'] >= 3)
                & (data['eridwarf'] >= data['dsalix']) & (data['dryas'] >= (data['eridwarf'] * 0.5)),
                171, type_data)

            # 174. Alaska-Yukon Ericaceous Dwarf Shrub
            type_data = np.where(
                (type_data == 5001)
                & ((data['ndshrub'] < 5) | (data['surficial'] == 2))
                & ((data['dryas'] >= 3) | (data['eridwarf'] >= 3))
                & (data['eridwarf'] >= data['dsalix']) & (data['dryas'] < (data['eridwarf'] * 0.5)),
                174, type_data)

            # 185. Alaska-Yukon Post-burn Birch-Willow Mesic
            type_data = np.where(
                (type_data == 5001) & (data['fire'] >= 1984) & (data['surficial'] != 8)
                & ((data['ndsalix'] + data['betshr']) >= 5),
                185, type_data)

            # 244. Alaska-Yukon Post-Burn Recovering Birch-Willow Wet
            type_data = np.where(
                (type_data == 5002) & (data['fire'] >= 1984) & (data['surficial'] != 8)
                & ((data['ndsalix'] + data['betshr']) >= 5),
                244, type_data)

            # 221. Alaska-Yukon Alder-Willow Active Floodplain
            type_data = np.where(
                (np.isin(type_data, [5001, 5002])) & (data['surficial'] == 8)
                & (data['ndsalix'] >= 5) & (data['alnus'] >= 5)
                & (data['alnus'] >= (data['ndsalix'] * 0.5)),
                221, type_data)

            # 222. Alaska-Yukon Willow Active Floodplain
            type_data = np.where(
                (np.isin(type_data, [5001, 5002])) & (data['surficial'] == 8)
                & (data['ndsalix'] >= 5) & (data['alnus'] < (data['ndsalix'] * 0.5)),
                222, type_data)

            # 181. Alaska-Yukon Alder Mesic
            type_data = np.where(
                (type_data == 5001)
                & (data['alnus'] >= 5) & (data['alnus'] >= (data['ndsalix'] * 1.5)),
                181, type_data)

            # 182. Alaska-Yukon Alder-Willow Mesic
            type_data = np.where(
                (type_data == 5001)
                & (data['alnus'] >= 5)
                & (data['alnus'] < (data['ndsalix'] * 1.5)) & (data['alnus'] >= (data['ndsalix'] * 0.5)),
                182, type_data)

            # 186. Alaska-Yukon Willow Mesic
            type_data = np.where(
                (type_data == 5001)
                & (data['ndsalix'] >= 5)
                & (data['alnus'] < (data['ndsalix'] * 0.5)) & (data['ndsalix'] >= (data['betshr'] * 1.5)),
                186, type_data)

            # 184. Alaska-Yukon Birch-Willow Mesic
            type_data = np.where(
                (type_data == 5001)
                & (data['betshr'] >= 5)
                & (data['ndsalix'] >= (data['erishrub'] * 0.8)) & (data['ndsalix'] < (data['betshr'] * 1.5)),
                184, type_data)

            # 183. Alaska-Yukon Ericaceous (-Birch) Mesic
            type_data = np.where(
                (type_data == 5001)
                & (data['erishrub'] >= 5)
                & (data['ndsalix'] < (data['erishrub'] * 0.8)),
                183, type_data)

            # 243. Alaska-Yukon Alder-Willow Wet
            type_data = np.where(
                (type_data == 5002)
                & (data['alnus'] >= 5)
                & (data['alnus'] >= (data['ndsalix'] * 0.5)),
                243, type_data)

            # 242. Alaska-Yukon Willow Wet
            type_data = np.where(
                (type_data == 5002)
                & (data['ndsalix'] >= 5)
                & (data['alnus'] < (data['ndsalix'] * 0.5)) & (data['ndsalix'] >= (data['betshr'] * 1.5)),
                242, type_data)

            # 241. Alaska-Yukon Birch-Willow Wet
            type_data = np.where(
                (type_data == 5002)
                & (data['betshr'] >= 5)
                & (data['ndsalix'] < (data['betshr'] * 1.5)),
                241, type_data)

            # 204. Alaska-Yukon Shrub-Sphagnum Peatland, Ombrotrophic
            type_data = np.where(
                (type_data == 5003)
                & (data['sphagn'] >= 15) & (data['ndshrub'] >= 15) & (data['erivag'] < 15),
                204, type_data)

            # 201. Alaska-Yukon (Dwarf Shrub) Sedge-Sphagnum Peatland, Ombrotrophic
            type_data = np.where(
                (type_data == 5003)
                & (data['sphagn'] >= 15) & (data['ndshrub'] < 15) & (data['erivag'] < 15),
                201, type_data)

            # 205. Alaska-Yukon Tussock Peatland, Ombrotrophic
            type_data = np.where(
                (type_data == 5003) & (data['erivag'] >= 15),
                205, type_data)

            # 207. Alaska-Yukon Shrub-Sedge Peatland, Minerotrophic
            type_data = np.where(
                (type_data == 5003) & (data['sphagn'] < 15) & (data['erivag'] < 15),
                207, type_data)

            #### KEY BOREAL HERBACEOUS TYPES
            ####____________________________________________________

            # 294. Arctic Ericaceous (-Birch) Lichen Tundra
            type_data = np.where(
                (type_data == 6001) & (data['surficial'] != 2)
                & (((data['lichen'] >= 35) & (data['fire'] < 1980))
                   | ((data['lichen'] >= 45) & (data['fire'] < 2019))),
                294, type_data)

            # 175. Alaska-Yukon Alpine Meadow Mesic
            type_data = np.where(
                (type_data == 6001) & (data['surficial'] == 2),
                175, type_data)

            # 223. Alaska-Yukon Herbaceous Active Floodplain
            type_data = np.where(
                (type_data == 6001) & (data['surficial'] == 8),
                223, type_data)

            # 191. Alaska-Yukon Calamagrostis-Forb Meadow Mesic
            type_data = np.where(
                (type_data == 6001) & (data['mwcalama'] >= 15),
                191, type_data)

            # 192. Alaska-Yukon Forb-Graminoid Meadow Mesic Acidic
            type_data = np.where(
                (type_data == 6001) & (data['mwcalama'] < 15),
                192, type_data)

            # 226. Alaska-Yukon Sedge-Calamagrostis Wet Meadow (Mineral/Riverine)
            type_data = np.where(
                (type_data == 6002) & (data['mwcalama'] >= 20),
                226, type_data)

            # 225. Alaska-Yukon Sedge Wet Meadow (Mineral/Riverine)
            type_data = np.where(
                (type_data == 6002) & (data['mwcalama'] < 20) & (data['wetsed'] >= 15),
                225, type_data)

            # 227. Alaska-Yukon Forb-Graminoid Meadow Wet (Mineral/Riverine)
            type_data = np.where(
                (type_data == 6002) & (data['mwcalama'] < 20) & (data['wetsed'] < 15),
                227, type_data)

            # 201. Alaska-Yukon (Dwarf Shrub) Sedge-Sphagnum Peatland, Ombrotrophic
            type_data = np.where(
                (type_data == 6003) & (data['sphagn'] >= 15),
                201, type_data)

            # 206. Alaska-Yukon Sedge Peatland, Minerotrophic
            type_data = np.where(
                (type_data == 6003) & (data['sphagn'] < 15),
                206, type_data)

            #### APPLY CORRECTIONS
            ####____________________________________________________

            # 999. recently burned
            type_data = np.where(
                (~np.isin(type_data, [995, 996, 998, 176, 224, 250])) & (data['burned'] == 1),
                999, type_data)

            # Convert 294 to 173
            type_data = np.where(type_data == 294, 173, type_data)

            # Convert 272 and 274 to 205
            type_data = np.where(
                (type_data == 272) | (type_data == 274),
                205, type_data)

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
                (sieve_data == 0) | (sieve_data >= 1000),
                nodata_value, sieve_data)
            nibble_data = categorical_nibble(sieve_data, nodata_value)

            # Apply sieve
            print('\tApplying size threshold...')
            sieve_data = features.sieve(nibble_data.astype('int16'), size=200, connectivity=4)
            sieve_data = features.sieve(sieve_data.astype('int16'), size=200, connectivity=4)

            # Generalize the raster shapes with majority filter
            print('\tApplying majority filter...')
            filter_data = apply_smoothing_filter(sieve_data, window_size=5, iterations=3)
            filter_data = apply_smoothing_filter(filter_data, window_size=3, iterations=2)

            # Add omitted data into final raster
            print('\tAdding omitted data...')
            combine_data = np.where(omitted_mask, type_data, filter_data)

            # Apply sieve
            print('\tApplying size threshold...')
            sieve_data = features.sieve(combine_data.astype('int16'), size=20, connectivity=4)
            sieve_data = features.sieve(sieve_data.astype('int16'), size=20, connectivity=4)

            # Generalize the raster shapes with majority filter
            print('\tApplying majority filter...')
            filter_data = apply_smoothing_filter(sieve_data, window_size=3, iterations=1)

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
        end_timing(start_time)
    else:
        print(f'{grid} already exists.')

    # Increase count
    grid_count += 1

# Close all raster connections
for src in raster_sources.values():
    src.close()
topo_source.close()
foliar_source.close()
chm_source.close()

#### PROCESS CLOUD-OPTIMIZED GEOTIFF
####____________________________________________________

# Create merged VRT raster
input_files = glob.glob(os.path.join(tiles_folder, '*.tif'))

# Merge raster tiles
print(f'Merging {len(input_files)} tiles to cloud-optimized geotiff...')
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
cog_data = gdal.Translate(type_output, vrt_intermediate, options=cog_options)
cog_data = None
end_timing(start_time)

# Remove intermediate datasets
if os.path.exists(vrt_intermediate):
    os.remove(vrt_intermediate)

# Upload post-processed raster to GCS
start_time = time.time()
print('Uploading cloud-optimized geotiff to Google Cloud...')
upload_to_gcs(type_output, final_gcs_output, storage_client)
end_timing(start_time)

#### BUILD RASTER ATTRIBUTE TABLE
####____________________________________________________

# Specify attribute table file path
attribute_output = type_output + '.vat.dbf'
if os.path.exists(attribute_output):
    os.remove(attribute_output)

# Define new collection counter
value_counts = collections.Counter()

# Read raster blocks to build attribute values and counts
print('Building value histogram...')
start_time = time.time()
with rasterio.open(type_output) as type_raster:
    # Find number of raster blocks
    window_list = [window for block_index, window in type_raster.block_windows(1)]

    # Establish raster counts
    count = 1
    progress = 0

    # Create attribute count
    for block_index, window in type_raster.block_windows(1):
        # Read input data
        input_block = type_raster.read(1, window=window, masked=True)

        # Use compressed to ignore nodata
        input_data = input_block.compressed()
        if input_data.size == 0:
            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)
        else:
            # Update the histogram incrementally
            value_counts.update(input_data.tolist())
            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)

# Raise error for empty output
if not value_counts:
    raise RuntimeError('Raster contains no valid data.')

# Convert counter to sorted lists
print('Building raster attribute table...')
unique_values = sorted(value_counts.keys())

# Define DBF table fields
attribute_table = dbf.Table(
    attribute_output,
    'VALUE N(10,0); COUNT N(20,0); MAP_CLS C(254); COARSE_CLS C(254); PEATLAND C(254); MACRO_CODE C(50); NVC_MACRO C(254); GROUP_CODE C(50); NVC_GROUP C(254)',
    codepage='utf8'
)

# Read the schema data
schema_data = pd.read_csv(schema_input).fillna('')

# Convert the dataframe to a dictionary using 'code' as the key for fast row lookups
schema_dict = schema_data.set_index('code').to_dict(orient='index')

# Write attribute table
attribute_table.open(mode=dbf.READ_WRITE)
for value in unique_values:
    count = value_counts[value]

    # Retrieve the attributes for the current value, defaulting to empty strings if code is missing
    if int(value) in schema_dict:
        row = schema_dict[int(value)]
        map_class = str(row.get('map_class', ''))
        coarse_class = str(row.get('coarse_class', ''))
        peatland = str(row.get('peatland', ''))
        macrogroup_code = str(row.get('macrogroup_code', ''))
        macrogroup = str(row.get('macrogroup', ''))
        group_code = str(row.get('group_code', ''))
        group = str(row.get('group', ''))
    else:
        map_class = coarse_class = peatland = macrogroup_code = macrogroup = group_code = group = ''

    # Append the row matching the dbf field definition sequence
    attribute_table.append((
        int(value),
        int(count),
        map_class,
        coarse_class,
        peatland,
        macrogroup_code,
        macrogroup,
        group_code,
        group
    ))
attribute_table.close()
end_timing(start_time)

# Upload post-processed attribute table to GCS
start_time = time.time()
print('Uploading attribute table to Google Cloud...')
attribute_gcs_output = f'{gcs_base}/veg_types/{os.path.split(attribute_output)[1]}'
upload_to_gcs(attribute_output, attribute_gcs_output, storage_client)
end_timing(start_time)

# Create a .cpg file to guarantee ArcGIS Pro reads the encoding correctly
cpg_output = type_output + '.vat.cpg'
with open(cpg_output, 'w') as cpg_file:
    cpg_file.write('UTF-8')
cpg_gcs_output = f'{gcs_base}/veg_types/{os.path.split(cpg_output)[1]}'
upload_to_gcs(cpg_output, cpg_gcs_output, storage_client)
