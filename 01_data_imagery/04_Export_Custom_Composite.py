# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Export custom composite imagery
# Author: Timm Nawrocki
# Last Updated: 2026-10-15
# Usage: Must be executed in a Python 3.11+ installation with GDAL 3.9+.
# Description: 'Export custom composite imagery' exports an image asset to Google Cloud Storage. The composite image was created through a separate VHR pipeline repository.
# ---------------------------------------------------------------------------

# Import packages
import ee

#### SET UP GEE ENVIRONMENT
####____________________________________________________

# Define paths
ee_project = 'akveg-map'
storage_bucket = 'regional-nomebeaver'

# Authenticate with Earth Engine
print('Requesting information from server...')
ee.Authenticate()
ee.Initialize(project=ee_project)

# Define inputs and outputs
image_input = f'projects/{ee_project}/assets/reflectance_vhr/nome_beaver_ms_srlite_mosaic_02p00m'
region_input = f'projects/{ee_project}/assets/study_areas/nomebeaver_domain_3338'

# Set target resolution
scale = 2

#### LOAD RASTER
####____________________________________________________

# Load image
print('Loading image and extracting parameters...')
composite_2m = ee.Image(image_input)

# Select bands for export
composite_2m = composite_2m.select(
    ['blue', 'green', 'red', 'nir']
)

# Load the vector asset to define the export footprint
region_feature = ee.FeatureCollection(region_input)
region_geometry = region_feature.geometry()

# Get projection components
proj_info = composite_2m.select(0).projection().getInfo()
crs = proj_info['crs']
transform = proj_info['transform']

#### EXPORT RESULTS
####____________________________________________________

print('Initiating export task to Google Cloud Storage...')
task = ee.batch.Export.image.toCloudStorage(
    image=composite_2m,
    description='Nome-Beaver Composite Image',
    bucket=storage_bucket,
    fileNamePrefix='imagery/export/composite_orig_2m_3338',
    region=region_geometry,
    scale=scale,
    crs=crs,
    crsTransform=transform,
    maxPixels=1e13,
    formatOptions={'cloudOptimized': True}
)
task.start()
print(f'Task successfully started.')
