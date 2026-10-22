# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Predict surface water model
# Author: Timm Nawrocki
# Last Updated: 2026-10-22
# Usage: Must be executed in a Python 3.12+ installation.
# Description: 'Predict surface water model' predicts a trained hurdle model to create a map of surface water percentage.
# ---------------------------------------------------------------------------

# Define model targets
group = 'surfwater'
presence_threshold = 1

# Import packages
import os
import time
import numpy as np
import pandas as pd
import rasterio
import joblib
from osgeo import gdal
from google.cloud import storage
from akutils import *

# Define nodata value
nodata_value = -128

# Set random state
random_state = 314

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Define final GCS path for the output
output_name = 'surface_water_2m_3338.tif'
final_gcs_output = f'{gcs_base}/water_data/{output_name}'

# Set root directory
drive = '/home'
root_folder = 'twnawrocki'

# Define folder structure
region_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/region_data')
model_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/water_model')
covariate_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/covariate_data')
image_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/imagery')
output_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/water_data')

# Define input files
area_input = os.path.join(region_folder, 'nomebeaver_domain_2m_3338.tif')
threshold_input = os.path.join(model_folder, f'{group}_threshold_final.txt')
classifier_input = os.path.join(model_folder, f'{group}_classifier.joblib')
regressor_input = os.path.join(model_folder, f'{group}_regressor.joblib')
zonal_input = os.path.join(covariate_folder, 'covariates_zonal_2m_3338.tif')
image_input = os.path.join(image_folder, 'composite_2m_3338.tif')

# Define intermediate files
water_intermediate = os.path.join(output_folder, 'water_inter_2m_3338.tif')

# Define output files
water_output = os.path.join(output_folder, output_name)

#### PREPARE MODEL AND COVARIATES
####____________________________________________________

# Load classifier
print('Loading model and identifying features...')
classifier = joblib.load(classifier_input)
regressor = joblib.load(regressor_output)

# Read threshold
with open(threshold_input, "r") as threshold_reader:
    threshold = float(threshold_reader.readlines()[0])

# Retrieve exact feature names and order expected by trained model
model_features = list(classifier.feature_names_in_)

# Define image composite predictor names
predictor_comp = ['comp_blue', 'comp_green', 'comp_red', 'comp_nir', 'comp_ndwi', 'comp_ndvi']

# Separate zonal predictors from composite predictors
predictor_zonal = [feat for feat in model_features if feat not in predictor_comp]

# Identify band indices for zonal input raster
with rasterio.open(zonal_input) as src:
    raster_band_map = {desc: idx for idx, desc in enumerate(src.descriptions, start=1) if desc}
    try:
        selected_bands = [raster_band_map[name] for name in predictor_zonal]
    except KeyError as e:
        raise KeyError(f'Requested zonal predictor {e} was not found in raster band descriptions.')

#### RUN MODEL PREDICTION
####____________________________________________________
print('Predicting output raster...')
start_time = time.time()

# Prepare output profile
area_raster = rasterio.open(area_input)
output_profile = area_raster.profile.copy()
output_profile.update({
        'count': 1,
        'nodata': nodata_value,
        'dtype': 'int8',
        'compress': 'lzw',
        'bigtiff': 'YES',
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512
    })

# Prepare raster data
zonal_raster = rasterio.open(zonal_input)
image_raster = rasterio.open(image_input)

# Predict model results by raster block
with rasterio.open(water_intermediate, 'w', **output_profile) as dst:
    # Initiate raster block count
    window_list = [window for block_index, window in area_raster.block_windows(1)]
    count = 1
    progress = 0

    # Predict each block
    for block_index, window in area_raster.block_windows(1):
        # Read study area block
        area_data = area_raster.read(1, window=window)
        rows, cols = area_block.shape

        # Skip prediction if block contains no valid study area pixels
        if not np.any(area_block == 1):
            response_2d = np.full((rows, cols), nodata_value, dtype=np.int8)
            dst.write(response_2d, window=window, indexes=1)
            count, progress = raster_block_progress(100, len(window_list), count, progress)
            continue

        # Read selected zonal covariate bands (3D: bands, rows, cols)
        zonal_block = zonal_raster.read(indexes=selected_bands, window=window)

        # Read image composite bands (3D: bands, rows, cols)
        image_block = image_raster.read(window=window)
        comp_blue = image_block[0]
        comp_green = image_block[1]
        comp_red = image_block[2]
        comp_nir = image_block[3]

        # Calculate normalized difference indices
        comp_ndwi = calc_normalized_index(comp_green, comp_nir)
        comp_ndvi = calc_normalized_index(comp_nir, comp_red)

        # Reshape spatial blocks into 2D tabular features (pixels, features)
        n_pixels = rows * cols
        zonal_2d = zonal_block.reshape(len(selected_bands), n_pixels).T
        image_2d = np.column_stack([
            comp_blue.ravel(),
            comp_green.ravel(),
            comp_red.ravel(),
            comp_nir.ravel(),
            comp_ndwi.ravel(),
            comp_ndvi.ravel()
        ])

        # Combine zonal and image features into single array
        X_array = np.hstack([zonal_2d, image_2d])

        # Build covariate dataframe with proper column headers and order
        X_data = pd.DataFrame(X_array, columns=predictor_zonal + predictor_comp)
        X_data = X_data[model_features].fillna(0)

        # Predict response using the explicitly ordered DataFrame
        response_probability = np.array(classifier.predict_proba(X_data)[:, 1])
        response_abundance = np.array(regressor.predict(X_data))

        # Apply thresholds
        response_output = np.where(response_probability >= threshold, response_abundance, 0)
        response_output = np.where(response_output < presence_threshold, 0, response_output)
        response_output = np.where(response_output > 100, 100, response_output)

        # Reshape 1D prediction back to 2D spatial block
        response_2d = np.round(response_output, 0).reshape(rows, cols).astype(np.int8)

        # Extract to study area
        response_2d = np.where(area_data == 1, response_2d.astype('int8'), nodata_value)

        # Write results
        dst.write(response_2d, window=window, indexes=1)

        # Report progress
        count, progress = raster_block_progress(100, len(window_list), count, progress)

    end_timing(start_time)

# Close rasters
for raster in [area_raster, zonal_raster, image_raster]:
    raster.close()

#### EXPORT CLOUD-OPTIMIZED GEOTIFF
####____________________________________________________

# Set translation options for GDAL COG driver
cog_options = gdal.TranslateOptions(
    format='COG',
    creationOptions=[
        'COMPRESS=DEFLATE',
        'PREDICTOR=YES',
        'BLOCKSIZE=512',
        'NUM_THREADS=ALL_CPUS',
        'BIGTIFF=YES',
        'RESAMPLING=AVERAGE',
        'OVERVIEW_RESAMPLING=AVERAGE'
    ]
)

# Translate raster to cloud-optimized geotiff
print('Converting to cloud-optimized geotiff...')
start_time = time.time()
cog_data = gdal.Translate(water_output, water_intermediate, options=cog_options)
cog_data = None
end_timing(start_time)

# Remove intermediate datasets
if os.path.exists(water_intermediate):
    os.remove(water_intermediate)

# Upload post-processed raster to GCS
start_time = time.time()
print('Uploading cloud-optimized geotiff to Google Cloud...')
upload_to_gcs(water_output, final_gcs_output, storage_client)
end_timing(start_time)
