# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Extract covariates to training points
# Author: Timm Nawrocki
# Last Updated: 2026-10-15
# Usage: Must be executed in a Python 3.12+ installation.
# Description: 'Extract covariates to training points' aggregates training data to labeled points and extracts covariates from raster stacks.
# ---------------------------------------------------------------------------

# Import packages
import os
import time
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from akutils import *

# Define nodata value
nodata_value = -32768

# Set random state
random_state = 314

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
region_geopackage = os.path.join(project_folder, 'data_input/region_data/region_data_3338.gpkg')
surficial_folder = os.path.join(project_folder, 'data_input/surficial_data')
manual_geopackage = os.path.join(surficial_folder, 'surficial_training_manual_3338.gpkg')
training_geopackage = os.path.join(surficial_folder, 'surficial_training_3338.gpkg')
segment_folder = os.path.join(project_folder, 'data_input/segment_data')
image_folder = os.path.join(project_folder, 'data_input/imagery')

# Define input files
domain_layer = 'nomebeaver_domain_3338'
alpbare_layer = 'surficial_training_alpinebare_3338'
alpine_layer = 'surficial_training_alpine_3338'
lowland_layer = 'surficial_training_lowland_3338'
bare_layer = 'surficial_training_bare_3338'
water_layer = 'surficial_training_water_3338'
zonal_input = os.path.join(segment_folder, 'zonal_stats_2m_3338.tif')
image_input = os.path.join(image_folder, 'composite_2m_3338.tif')

# Define output files
training_layer = 'surficial_training_3338'

#### AGGREGATE RANDOM POINTS
####____________________________________________________

# Read vector data
print('Sampling and merging training point data...')
start_time = time.time()
domain_data = gpd.read_file(region_geopackage, layer=domain_layer)
alpbare_data = gpd.read_file(manual_geopackage, layer=alpbare_layer).clip(domain_data)
alpine_data = gpd.read_file(manual_geopackage, layer=alpine_layer).clip(domain_data)
lowland_data = gpd.read_file(manual_geopackage, layer=lowland_layer).clip(domain_data)
bare_data = gpd.read_file(manual_geopackage, layer=bare_layer).clip(domain_data)
water_data = gpd.read_file(manual_geopackage, layer=water_layer).clip(domain_data)

# Label point datasets
alpbare_data['class'] = 1
alpine_data['class'] = 2
lowland_data['class'] = 3
bare_data['class'] = 4
water_data['class'] = 5

# Sample point datasets to 2000
alpbare_sample = alpbare_data.sample(n=2000, random_state=random_state)
alpine_sample = alpine_data.sample(n=2000, random_state=random_state)
bare_sample = bare_data.sample(n=2000, random_state=random_state)
water_sample = water_data.sample(n=2000, random_state=random_state)

# Sample lowland point dataset to 4000
lowland_sample = lowland_data.sample(n=4000, random_state=random_state)

# Merge point datasets
merged_data = gpd.GeoDataFrame(pd.concat([
    alpbare_sample,
    alpine_sample,
    lowland_sample,
    bare_sample,
    water_sample
], ignore_index=True), crs=domain_data.crs)
end_timing(start_time)

#### EXTRACT ZONAL COVARIATES
####____________________________________________________

# Define covariate sets
print('Identifying covariate set...')
predictor_topo = ['coast', 'stream', 'river', 'wetness',
                  'elevation', 'exposure', 'heatload', 'position',
                  'aspect', 'relief', 'roughness', 'slope']
predictor_s1 = ['s1_1_vha', 's1_1_vhd', 's1_1_vva', 's1_1_vvd',
                's1_2_vha', 's1_2_vhd', 's1_2_vva', 's1_2_vvd',
                's1_3_vha', 's1_3_vhd', 's1_3_vva', 's1_3_vvd']
predictor_s2 = [f's2_{i}_{band}' for i in range(1, 6) for band in
                ['blue', 'green', 'red', 'redge1', 'redge2', 'redge3', 'nir',
                 'redge4', 'swir1', 'swir2', 'nbr', 'ngrdi', 'ndmi', 'ndsi',
                 'ndvi', 'ndwi']]

# Dynamically build predictor_all list from input arguments
predictor_names = ['topo', 's1', 's2']
predictor_map = {
    'topo': predictor_topo,
    's1': predictor_s1,
    's2': predictor_s2,
}
predictor_all = []
for name in predictor_names:
    if name in predictor_map:
        predictor_all.extend(predictor_map[name])
    else:
        print(f'Warning: Predictor set {name} not recognized and will be skipped.')
if not predictor_all:
    raise ValueError('No valid predictor sets were provided. Exiting.')

# Identify coordinates from the clipped point data
print('Extracting zonal covariates...')
start_time = time.time()
coordinates = [(x, y) for x, y in zip(merged_data.geometry.x, merged_data.geometry.y)]

# Extract raster values
with rasterio.open(zonal_input) as src:
    # Build raster band map
    raster_band_map = {desc: idx for idx, desc in enumerate(src.descriptions, start=1) if desc}

    # Identify the specified raster bands
    try:
        selected_bands = [raster_band_map[name] for name in predictor_all]
    except KeyError as e:
        raise KeyError(f'Requested predictor {e} was not found in the raster band descriptions.')

    # Sample the raster at the provided coordinates
    extracted_values = list(src.sample(coordinates, indexes=selected_bands))

# Build dataframe from extracted values
zonal_data = pd.DataFrame(np.array(extracted_values), columns=predictor_all, index=merged_data.index)
merged_data = pd.concat([merged_data, zonal_data], axis=1)
end_timing(start_time)

#### EXTRACT IMAGE COVARIATES
####____________________________________________________

# Extract raster values for comp_blue, comp_green, comp_red, and comp_nir to points
print('Extracting image covariates...')
start_time = time.time()
with rasterio.open(image_input) as src:
    image_values = list(src.sample(coordinates))

# Convert results to numpy array
image_array = np.array(image_values)
comp_blue = image_array[:, 0]
comp_green = image_array[:, 1]
comp_red = image_array[:, 2]
comp_nir = image_array[:, 3]

# Calculate normalized difference indices
comp_ndwi = calc_normalized_index(comp_green, comp_nir)
comp_ndvi = calc_normalized_index(comp_nir, comp_red)

# Construct image covariates DataFrame and concatenate at once
image_data = pd.DataFrame({
    'comp_blue': comp_blue,
    'comp_green': comp_green,
    'comp_red': comp_red,
    'comp_nir': comp_nir,
    'comp_ndwi': comp_ndwi,
    'comp_ndvi': comp_ndvi
}, index=merged_data.index)
merged_data = pd.concat([merged_data, image_data], axis=1)

#### FILTER AND EXPORT DATA
####____________________________________________________

# Drop nodata or null values
valid_mask = ~(merged_data == nodata_value).any(axis=1) & ~merged_data.isna().any(axis=1)
export_data = merged_data[valid_mask].copy()

# Export the final geodataframe
print(f'Exporting {len(export_data)} points...')
export_data.to_file(training_geopackage, layer=training_layer, driver='GPKG')
end_timing(start_time)
