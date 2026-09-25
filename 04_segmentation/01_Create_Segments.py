# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Create image segments
# Author: Dan Wexler, Matt Macander, Timm Nawrocki
# Last Updated: 2026-08-29
# Usage: Must be executed in a Python 3.11+ installation with GDAL 3.9+.
# Description: 'Create image segments' calculates image segments and then iteratively merges adjacent segments with similar spectral properties.
# ---------------------------------------------------------------------------

# Import packages
import ee
from akutils import *

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
image_input = f'gs://{storage_bucket}/{storage_prefix}/imagery/composite_2m_3338.tif'
region_input = f'projects/{ee_project}/assets/study_areas/NomeBeaver_MapDomain_3338'

# Set target resolution
scale = 2

#### LOAD AND PRE-PROCESS RASTER
####____________________________________________________

# Load image
print('Loading image and region...')
composite_2m = ee.Image.loadGeoTIFF(image_input)

# Load the vector asset to define the export footprint
region_feature = ee.FeatureCollection(region_input)
region_geometry = region_feature.geometry()

# Get projection components
proj_info = composite_2m.projection().getInfo()
crs = proj_info['crs']
transform = proj_info['transform']

# Select bands for segmentation
input_image = composite_2m.select(
    ['B0', 'B1', 'B2', 'B3'],
    ['blue', 'green', 'red', 'nir']
)

# Apply Gaussian smoothing to mitigate image imperfections, shadows, and contamination
print('Applying Gaussian smoothing...')
gaussian_kernel = ee.Kernel.gaussian(
    radius=1,
    sigma=0.75,
    units='pixels',
    normalize=True
)
smoothed_image = input_image.convolve(gaussian_kernel)

# Calculate NDVI and create segmentation base image
ndvi_image = smoothed_image.normalizedDifference(['nir', 'red']).rename('ndvi')
segmentation_image = smoothed_image.toFloat().divide(255).addBands(ndvi_image)

#### EXECUTE SEGMENTATION PIPELINE
####____________________________________________________

# Calculate initial clusters using simple non-iterative clustering
print('Running SNIC segmentation and merging operations...')
segments = ee.Algorithms.Image.Segmentation.SNIC(
    image=segmentation_image,
    size=10,
    compactness=1/255,
    connectivity=4,
    neighborhoodSize=128
)
clusters = segments.select('clusters')

# Conduct two iterations of spectral merging and one iteration of size merging
clusters = merge_spectral(clusters, segmentation_image, 0.005)
clusters = merge_spectral(clusters, segmentation_image, 0.005)
clusters = merge_size(clusters, 5)

#### EXPORT RESULTS
####____________________________________________________

print('Initiating export task to Google Cloud Storage...')
task = ee.batch.Export.image.toCloudStorage(
    image=clusters,
    description='Nome-Beaver Segments',
    bucket=storage_bucket,
    fileNamePrefix=f'{storage_prefix}/segments/export/segments_2m_3338',
    region=region_geometry,
    scale=scale,
    crs=crs,
    crsTransform=transform,
    maxPixels=1e13,
    formatOptions={'cloudOptimized': True}
)
task.start()
print(f'Task successfully started.')
