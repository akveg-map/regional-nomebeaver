# Import packages
import os
import time
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
chm_folder = os.path.join(project_folder, 'data_output/height_data')
output_folder = os.path.join(project_folder,
                             'data_output/data_package/20261029_NomeBeaver_DataPackage/height_data')

# Define input files
chm_input = os.path.join(chm_folder, 'chm_segments_2m_3338_v20261020.tif')

# Define target bands and corresponding output file names
target_bands = {'chm_mean_cm': 'canopy_height_cm_mean_2m_3338.tif',
                'chm_rh90_cm': 'canopy_height_cm_rh90_2m_3338.tif'}

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

src_ds = gdal.Open(chm_input)

for band_idx in range(1, src_ds.RasterCount + 1):
    band = src_ds.GetRasterBand(band_idx)
    band_name = band.GetDescription()

    if band_name in target_bands:
        output_file = target_bands[band_name]
        chm_output = os.path.join(output_folder, output_file)

        print(f'Translating {band_name} ({band_idx})...')
        start_time = time.time()

        # Set translation options specifying single band extraction
        cog_options = gdal.TranslateOptions(
            format='COG',
            bandList=[band_idx],
            creationOptions=cog_creation_options
        )

        # Translate raster band directly to Cloud Optimized GeoTIFF
        cog_ds = gdal.Translate(chm_output, src_ds, options=cog_options)
        cog_ds = None

        end_timing(start_time)

src_ds = None
