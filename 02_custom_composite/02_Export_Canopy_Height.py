# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Export canopy height
# Author: Timm Nawrocki
# Last Updated: 2026-08-28
# Usage: Must be executed in a Python 3.11+ installation with GDAL 3.9+.
# Description: 'Export canopy height' exports a raster map of canopy height to Google Cloud Storage. The canopy height map was created through a separate VHR pipeline repository.
# ---------------------------------------------------------------------------

# Import packages
import ee

#### SET UP GEE ENVIRONMENT
####____________________________________________________

# Define paths
ee_project = 'akveg-map'
storage_bucket = 'akveg-data'
storage_prefix = 'regional_nomebeaver'

# Authenticate with Earth Engine
print('Requesting information from server...')
ee.Authenticate()
ee.Initialize(project=ee_project)

# Define inputs and outputs
image_input = f'projects/{ee_project}/assets/reflectance_vhr/nome_beaver_chm_mosaic_00p50m'
region_input = f'projects/{ee_project}/assets/study_areas/NomeBeaver_MapDomain_3338'

# Set target resolution
scale = 2

#### LOAD AND DOWNSCALE RASTER
####____________________________________________________

# Load 0.5 m image
print('Loading CHM image and extracting parameters...')
chm_05m = ee.Image(image_input)

# Load the vector asset to define the export footprint
region_feature = ee.FeatureCollection(region_input)
region_geometry = region_feature.geometry()

# Get projection components
proj_info = chm_05m.select(0).projection().getInfo()
crs = proj_info['crs']

# Downscale to 2m using average resampling
print('Applying average reducer for downscaling...')
chm_2m = chm_05m.reduceResolution(
    reducer=ee.Reducer.mean(),
    maxPixels=1024 # Buffer to ensure all 0.5m pixels within a 2m cell are evaluated
)

#### EXPORT RESULTS
####____________________________________________________

print('Initiating export task to Google Cloud Storage...')
task = ee.batch.Export.image.toCloudStorage(
    image=chm_2m,
    description='Nome-Beaver CHM',
    bucket=storage_bucket,
    fileNamePrefix=f'{storage_prefix}/canopy_height/composite_chm_2m_3338',
    region=region_geometry,
    scale=scale,
    crs=crs,
    maxPixels=1e13,
    formatOptions={'cloudOptimized': True}
)
task.start()
print('Task successfully started.')
