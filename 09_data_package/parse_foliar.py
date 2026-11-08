# Import packages
import os
import time
import shutil
from osgeo import gdal
from akutils import *

# Configure GDAL
gdal.UseExceptions()

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = 'C:/'
root_folder = 'ACCS_Work'

# Define folder structure
project_folder = os.path.join(drive, root_folder, 'Projects/VegetationEcology/AKVEG_EVT_NomeBeaver/data')
covariate_folder = os.path.join(project_folder, 'data_input/covariate_data')
output_folder = os.path.join(project_folder,
                             'data_output/data_package/20261029_NomeBeaver_DataPackage/foliar_data')
template_folder = os.path.join(project_folder, 'data_input/templates')

# Define input files
foliar_input = os.path.join(covariate_folder, 'foliar_zonal_2m_3338.tif')
template_input = os.path.join(template_folder, 'colormap_template.clr')

# Define GDAL COG creation options
cog_creation_options = [
    'COMPRESS=DEFLATE',
    'PREDICTOR=YES',
    'BLOCKSIZE=512',
    'NUM_THREADS=ALL_CPUS',
    'BIGTIFF=YES',
    'RESAMPLING=AVERAGE',
    'OVERVIEW_RESAMPLING=AVERAGE'
]

#### SPLIT MULTI-BAND RASTER & TRANSLATE TO COG
####____________________________________________________

# Read input raster
src_ds = gdal.Open(foliar_input)

for band_idx in range(1, src_ds.RasterCount + 1):
    band = src_ds.GetRasterBand(band_idx)
    band_name = band.GetDescription()

    if not band_name:
        continue

    # Define file naming conventions
    output_file = f'{band_name}_2m_3338.tif'
    foliar_output = os.path.join(output_folder, output_file)
    colormap_output = os.path.join(output_folder, os.path.splitext(output_file)[0] + '.clr')

    print(f'Translating {band_name} ({band_idx})...')
    start_time = time.time()

    # Set translation options specifying single band extraction
    cog_options = gdal.TranslateOptions(
        format='COG',
        bandList=[band_idx],
        creationOptions=cog_creation_options
    )

    # Translate raster band directly to Cloud Optimized GeoTIFF
    cog_ds = gdal.Translate(foliar_output, src_ds, options=cog_options)
    cog_ds = None

    # Copy matching colormap template
    shutil.copyfile(template_input, colormap_output)
    end_timing(start_time)

src_ds = None
