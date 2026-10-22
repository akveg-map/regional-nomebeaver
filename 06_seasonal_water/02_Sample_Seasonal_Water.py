# ---------------------------------------------------------------------------
# Sample seasonal water points
# Author: Timm Nawrocki, Alaska Center for Conservation Science
# Last Updated: 2026-10-22
# Usage: Must be executed in a Python 3.12+ installation.
# Description: 'Sample seasonal water points' selects random training points from the summarized initial seasonal water raster corresponding to raster data ranges.
# ---------------------------------------------------------------------------

# Import libraries
import os
import time
import fiona
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, MultiPoint
import rasterio
from google.cloud import storage
from akutils import *

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Define final GCS path for the output
output_name = 'water_training_3338.gpkg'
final_gcs_output = f'{gcs_base}/water_training/{output_name}'

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
region_geopackage = os.path.join(project_folder, 'data_input/region_data/region_data_3338.gpkg')
group_layer = 'tiles_001_3338'
covariate_folder = os.path.join(project_folder, 'data_input/covariate_data')
image_folder = os.path.join(project_folder, 'data_input/imagery')
output_folder = os.path.join(project_folder, 'data_input/water_data')
output_geopackage = os.path.join(output_folder, output_name)

# Ensure output directory exists
os.makedirs(output_folder, exist_ok=True)

# Define input files
water_input = os.path.join(output_folder, 'seasonal_water_2m_3338.tif')
zonal_input = os.path.join(covariate_folder, 'covariates_zonal_2m_3338.tif')
image_input = os.path.join(image_folder, 'composite_2m_3338.tif')

# Define output layer
output_layer = 'seasonal_water_training_3338'

# Define sampling dictionary
sampling_dict = {
    (0, 0): 7000,
    (1, 24): 500,
    (25, 49): 500,
    (50, 74): 500,
    (75, 99): 500,
    (100, 100): 1000
}

# Delete output layer if it already exists
if os.path.exists(output_geopackage):
    try:
        if output_layer in fiona.listlayers(output_geopackage):
            fiona.remove(output_geopackage, layer=output_layer)
    except Exception:
        pass


#### DEFINE FUNCTIONS
####____________________________________________________

# Define a function to sample directly from raster value strata
def sample_from_raster_strata(raster_path,
                              min_val,
                              max_val,
                              target_count,
                              min_dist_m=20,
                              crs='EPSG:3338',
                              oversample_factor=3,
                              seed=42):
    '''
    Directly extracts pixel locations matching a specific raster value range, converts them to spatial
    points, and enforces minimum distance separation.

    Parameters:
    - raster_path: Path to the target raster file.
    - min_val: Minimum raster pixel value for stratum.
    - max_val: Maximum raster pixel value for stratum.
    - target_count: Target number of spatial points to return.
    - min_dist_m: Minimum distance required between points (in CRS units).
    - crs: Coordinate reference system.
    - oversample_factor: Multiplier to draw candidate points before spatial thinning.
    - seed: Random seed for reproducibility.

    Returns:
    - GeoDataFrame of stratified points containing 'water_cvr' pixel values.
    '''
    np.random.seed(seed)

    with rasterio.open(raster_path) as src:
        raster_data = src.read(1)
        transform = src.transform

        # Find matching pixel coordinates (row, col)
        rows, cols = np.where((raster_data >= min_val) & (raster_data <= max_val))
        total_matching = len(rows)

        if total_matching == 0:
            print(f'No pixels found in raster for range [{min_val}-{max_val}]. Skipping.')
            return gpd.GeoDataFrame({'geometry': [], 'water_cvr': []}, crs=crs)

        # Oversample to allow room for minimum distance thinning
        candidate_count = min(total_matching, target_count * oversample_factor)
        chosen_indices = np.random.choice(total_matching, size=candidate_count, replace=False)

        sel_rows = rows[chosen_indices]
        sel_cols = cols[chosen_indices]
        pixel_vals = raster_data[sel_rows, sel_cols]

        # Convert row/col pixel indices to spatial x/y coordinates (pixel centers)
        xs, ys = rasterio.transform.xy(transform, sel_rows, sel_cols, offset='center')

        # Filter candidates for minimum spatial distance
        kept_points = []
        kept_vals = []
        for x, y, val in zip(xs, ys, pixel_vals):
            pt = Point(x, y)
            if not kept_points:
                kept_points.append(pt)
                kept_vals.append(val)
            elif MultiPoint(kept_points).distance(pt) >= min_dist_m:
                kept_points.append(pt)
                kept_vals.append(val)

            # Exit loop as soon as target count is reached
            if len(kept_points) == target_count:
                break

        # Construct GeoDataFrame for current stratum
        stratum_data = gpd.GeoDataFrame({
            'geometry': kept_points,
            'water_cvr': kept_vals
        }, crs=crs)

        if len(stratum_data) < target_count:
            print(f'Only retained {len(stratum_data)} points out of {target_count} requested.')

    return stratum_data


#### GENERATE SAMPLES
####____________________________________________________

# Prepare empty list to store results
sample_points = []

# Generate stratified sample points directly from target raster ranges
for (min_val, max_val), target_count in sampling_dict.items():
    print(f'Sampling {target_count} points from range [{min_val}-{max_val}]...')
    start_time = time.time()
    stratum_gdf = sample_from_raster_strata(
        raster_path=water_input,
        min_val=min_val,
        max_val=max_val,
        target_count=target_count,
        min_dist_m=20,
        crs='EPSG:3338',
        oversample_factor=3
    )
    if not stratum_gdf.empty:
        sample_points.append(stratum_gdf)
    end_timing(start_time)

# Convert sample points to geodataframe
sample_data = gpd.GeoDataFrame(pd.concat(sample_points, ignore_index=True), crs='EPSG:3338')

# Extract the spatial coordinates
sample_data['cent_x'] = sample_data.geometry.x
sample_data['cent_y'] = sample_data.geometry.y

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
coordinates = [(x, y) for x, y in zip(sample_data.geometry.x, sample_data.geometry.y)]

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
zonal_data = pd.DataFrame(np.array(extracted_values), columns=predictor_all, index=sample_data.index)
sample_data = pd.concat([sample_data, zonal_data], axis=1)
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
}, index=sample_data.index)
sample_data = pd.concat([sample_data, image_data], axis=1)

#### PREPARE VALIDATION GROUPS
####____________________________________________________

# Read validation groups
group_data = gpd.read_file(region_geopackage, layer=group_layer)

# Create numerical group id
group_data = group_data.reset_index(names='valid')
group_data = group_data.drop(columns=['grid_code', 'shape_length', 'shape_area'])

# Spatial join validation ids to points
sample_data = gpd.sjoin(sample_data, group_data, how='left', predicate='intersects')

# Drop internal join index column if created
if 'index_right' in sample_data.columns:
    sample_data = sample_data.drop(columns=['index_right'])

#### FILTER AND EXPORT DATA
####____________________________________________________

# Drop nodata or null values
valid_mask = ~(sample_data == -32768).any(axis=1) & ~sample_data.isna().any(axis=1)
export_data = sample_data[valid_mask].copy()

# Export the final geodataframe using append mode to protect other layers
print(f'Exporting {len(export_data)} points to layer {output_layer}...')
export_data.to_file(output_geopackage, layer=output_layer, driver='GPKG', mode='a')
end_timing(start_time)

# Upload training data to GCS
start_time = time.time()
print('Uploading training data to Google Cloud...')
upload_to_gcs(output_geopackage, final_gcs_output, storage_client)
end_timing(start_time)
