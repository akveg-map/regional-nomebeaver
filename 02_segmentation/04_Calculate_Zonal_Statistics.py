# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Calculate zonal statistics
# Author: Timm Nawrocki
# Last Updated: 2026-10-15
# Usage: Must be executed in a Python 3.12+ installation.
# Description: "Calculate zonal statistics" reads cloud-optimized geotiffs from Google Cloud Storage to calculate per segment zonal statistics for 4-band VHR imagery, multi-seasonal Sentinel-1/2, topographic, hydrographic, and foliar cover covariates.
# ---------------------------------------------------------------------------

# Set environment
import os
os.environ['GDAL_GCS_BINARY_READ'] = 'YES'

# Import packages
import time
import numpy as np
from osgeo import gdal
import rasterio
from rasterio.enums import Resampling
from google.cloud import storage
from akutils import *

# Configure GDAL
gdal.UseExceptions()
gdal.SetCacheMax(1073741824) # Cap GDAL memory cache at 1 GB

# Define nodata value
nodata_value = -32768

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Initialize GCS Client
storage_client = storage.Client()

# Define GCS base name
gcs_base = 'gs://regional-nomebeaver'

# Define final GCS path for the output
output_name = 'zonal_stats_2m_3338.tif'
final_gcs_output = f'{gcs_base}/segment_data/{output_name}'

# Set root directory
drive = '/home'
root_folder = 'twnawrocki'

# Define folder structure
vrt_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/vrt_data')
segment_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/segment_data')

# Define input files
segment_input = os.path.join(segment_folder, 'segments_2m_3338.tif')

# Define intermediate files
s1_seasonal_vrt = os.path.join(vrt_folder, 's1_seasonal.vrt')
s2_seasonal_vrt = os.path.join(vrt_folder, 's2_seasonal.vrt')
s2_median_vrt = os.path.join(vrt_folder, 's2_median.vrt')

# Define intermediate files
zonal_intermediate = os.path.join(segment_folder, 'zonal_stats_int_2m_3338.tif')

# Define output files
zonal_output = os.path.join(segment_folder, output_name)

# Define covariate sets
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
predictor_foliar = ['alnus', 'betshr', 'bettre', 'dryas', 'dsalix',
                    'empnig', 'erivag', 'feather', 'forb', 'gramin',
                    'lichen', 'mwcalama', 'ndsalix', 'neetre', 'nerishr',
                    'picgla', 'picmar', 'poptre', 'populbt', 'rhoshr',
                    'sphagn', 'vaculi', 'vacvit', 'wetforb', 'wetsed']
predictor_dist = ['bromos', 'wetgram']
predictor_sum = ['eridwarf', 'erishrub', 'herbac', 'ndshrub', 'shrub', 'trees', 'wetind']
predictor_ratio = ['deciduous_ratio', 'picea_ratio', 'tussock_ratio']

# Dynamically build predictor_all list from input arguments
predictor_names = ['topo', 's1', 's2', 'foliar', 'dist', 'sum', 'ratio']
predictor_map = {
    'topo': predictor_topo,
    's1': predictor_s1,
    's2': predictor_s2,
    'foliar': predictor_foliar,
    'dist': predictor_dist,
    'sum': predictor_sum,
    'ratio': predictor_ratio
}
predictor_all = []
for name in predictor_names:
    if name in predictor_map:
        predictor_all.extend(predictor_map[name])
    else:
        print(f'Warning: Predictor set {name} not recognized and will be skipped.')
if not predictor_all:
    raise ValueError('No valid predictor sets were provided. Exiting.')

# Create band map
band_map = {name: i for i, name in enumerate(predictor_all, start=1)}

#### PREPARE RASTER COVARIATES
####____________________________________________________

# Set VRT configuration
vrt_options = gdal.BuildVRTOptions(resampleAlg='bilinear', resolution='highest')

# Define raster paths for environmental covariates
env_sources = {
    'coast': '/vsigs/akveg-data/covariates_v20240711/CoastDist_10m_3338.tif',
    'stream': '/vsigs/akveg-data/covariates_v20240711/StreamDist_10m_3338.tif',
    'river': '/vsigs/akveg-data/covariates_v20240711/RiverDist_10m_3338.tif',
    'wetness': '/vsigs/akveg-data/covariates_v20240711/Wetness_10m_3338.tif',
    'elevation': '/vsigs/akveg-data/covariates_v20240711/Elevation_10m_3338.tif',
    'exposure': '/vsigs/akveg-data/covariates_v20240711/Exposure_10m_3338.tif',
    'heatload': '/vsigs/akveg-data/covariates_v20240711/HeatLoad_10m_3338.tif',
    'position': '/vsigs/akveg-data/covariates_v20240711/Position_10m_3338.tif',
    'aspect': '/vsigs/akveg-data/covariates_v20240711/RadiationAspect_10m_3338.tif',
    'relief': '/vsigs/akveg-data/covariates_v20240711/Relief_10m_3338.tif',
    'roughness': '/vsigs/akveg-data/covariates_v20240711/Roughness_10m_3338.tif',
    'slope': '/vsigs/akveg-data/covariates_v20240711/Slope_10m_3338.tif'
}

# Define raster paths for S1 and S2 tiles
print('Compiling network paths...')
s1_paths = get_vsi_paths('akveg-data', 's1_2022_v20230326/', storage_client)
s2_seasonal_paths = get_vsi_paths('akveg-data', 's2_sr_2019_2023_gMedian_v20240713d/', storage_client)
s2_median_paths = get_vsi_paths('akveg-data', 's2_sr_2019_2023_median_v20240724/', storage_client)

# Define raster paths for foliar covariates
foliar_sources = {}
for name in predictor_foliar:
    foliar_sources[name] = f'/vsigs/akveg-data/foliar_cover_v2p1/rasters_final/{name}_cvr_10m_3338.tif'

# Define raster paths for distribution covariates
dist_sources = {}
for name in predictor_dist:
    dist_sources[name] = f'/vsigs/akveg-data/foliar_cover_v2p1/rasters_final/{name}_dst_10m_3338.tif'

# Define raster paths for sum covariates
sum_sources = {}
for name in predictor_sum:
    sum_sources[name] = f'/vsigs/akveg-data/foliar_cover_v2p1/rasters_summary/{name}_cvr_10m_3338.tif'

# Define raster paths for ratio covariates
ratio_sources = {}
for name in predictor_ratio:
    ratio_sources[name] = f'/vsigs/akveg-data/foliar_cover_v2p1/rasters_summary/{name}_10m_3338.tif'

# Create virtual raster for S1 covariates
if not os.path.exists(s1_seasonal_vrt):
    print('Building virtual raster for S1 covariates...')
    start_time = time.time()
    gdal.BuildVRT(s1_seasonal_vrt, s1_paths, options=vrt_options)
    end_timing(start_time)

# Create virtual raster for S2 seasonal covariates
if not os.path.exists(s2_seasonal_vrt):
    print('Building virtual raster for S2 seasonal covariates...')
    start_time = time.time()
    gdal.BuildVRT(s2_seasonal_vrt, s2_seasonal_paths, options=vrt_options)
    end_timing(start_time)

# Create virtual raster for S2 growing season median covariates
if not os.path.exists(s2_median_vrt):
    print('Building virtual raster for S2 median covariates...')
    start_time = time.time()
    gdal.BuildVRT(s2_median_vrt, s2_median_paths, options=vrt_options)
    end_timing(start_time)

#### CALCULATE BLOCK ZONAL STATISTICS
####____________________________________________________

# Identify maximum segment ID
print('Identifying segment raster for maximum ID...')
start_time = time.time()
max_seg_id = 0
with rasterio.open(segment_input) as segment_raster:
    for block_index, window in segment_raster.block_windows(1):
        segment_data = segment_raster.read(1, window=window)
        block_max = int(np.max(segment_data))
        if block_max > max_seg_id:
            max_seg_id = block_max
end_timing(start_time)

# Initialize accumulation arrays
sum_arrays = {b: np.zeros(max_seg_id + 1, dtype=np.float64) for b in predictor_all}
count_arrays = {b: np.zeros(max_seg_id + 1, dtype=np.int32) for b in predictor_all}

# Combine all single-band sources into one lookup
single_band_sources = {
    **env_sources,
    **foliar_sources,
    **dist_sources,
    **sum_sources,
    **ratio_sources
}

# Calculate zonal sums and counts
with rasterio.open(segment_input) as segment_raster:
    start_time = time.time()

    # Find number of raster blocks
    window_list = []
    for block_index, window in segment_raster.block_windows(1):
        window_list.append(window)

    # Establish raster count
    count = 1
    progress = 0

    # Identify nodata value
    segment_nodata = segment_raster.nodata if segment_raster.nodata is not None else 0

    # Retrieve metadata for S1 and S2 datasets
    with rasterio.open(s1_paths[0]) as s1_src:
        s1_descriptions = s1_src.descriptions
    with rasterio.open(s2_median_paths[0]) as s2_med_src:
        s2_backup_descriptions = s2_med_src.descriptions
    with rasterio.open(s2_seasonal_paths[0]) as s2_seas_src:
        s2_seasonal_descriptions = s2_seas_src.descriptions

    # Define band names for S1 data
    s1_translation = {
        'VH_p50_grow_asc': 's1_1_vha',
        'VH_p50_fall_asc': 's1_2_vha',
        'VH_p50_froz_asc': 's1_3_vha',
        'VV_p50_grow_asc': 's1_1_vva',
        'VV_p50_fall_asc': 's1_2_vva',
        'VV_p50_froz_asc': 's1_3_vva',
        'VH_p50_grow_desc': 's1_1_vhd',
        'VH_p50_fall_desc': 's1_2_vhd',
        'VH_p50_froz_desc': 's1_3_vhd',
        'VV_p50_grow_desc': 's1_1_vvd',
        'VV_p50_fall_desc': 's1_2_vvd',
        'VV_p50_froz_desc': 's1_3_vvd'
    }

    # Define band names for S2 data
    base_s2_bands = ['blue', 'green', 'red', 'redge1', 'redge2',
                     'redge3', 'nir', 'redge4', 'swir1', 'swir2']
    s2_map = {}
    for i, band in enumerate(s2_seasonal_descriptions, start=1):
        if band:
            band = band.replace('rededge', 'redge').replace('s2_seas1spring_', 's2_1_') \
                .replace('s2_seas2earlySummer_', 's2_2_').replace('s2_seas3midSummer_', 's2_3_') \
                .replace('s2_seas4lateSummer_', 's2_4_').replace('s2_seas5fall_', 's2_5_')
            s2_map[band] = i

    # Define band names for S2 backup
    s2_median_translation = {
        'B2': 's2_blue',
        'B3': 's2_green',
        'B4': 's2_red',
        'B5': 's2_redge1',
        'B6': 's2_redge2',
        'B7': 's2_redge3',
        'B8': 's2_nir',
        'B8A': 's2_redge4',
        'B11': 's2_swir1',
        'B12': 's2_swir2'
    }

    # Open single-band VRTs once before block loop
    single_band_vrts = {}
    for name, path in single_band_sources.items():
        if name in band_map:
            src_handle = rasterio.open(path)
            vrt_handle = rasterio.vrt.WarpedVRT(src_handle, crs='EPSG:3338', resampling=Resampling.bilinear)
            single_band_vrts[name] = (src_handle, vrt_handle)

    # Open multi-band VRTs once before block loop
    s1_raster = rasterio.open(s1_seasonal_vrt)
    s2_med_raster = rasterio.open(s2_median_vrt)
    s2_seas_raster = rasterio.open(s2_seasonal_vrt)

    try:
        # Calculate zonal statistics for each block in the segment raster
        print('Calculating zonal sums and counts across blocks...')
        for block_index, window in segment_raster.block_windows(1):
            # Read raster block
            segment_data = segment_raster.read(1, window=window)

            # Define the output profile based on master resolutions
            left, bottom, right, top = segment_raster.window_bounds(window)
            dst_height, dst_width = window.height, window.width

            # Dictionary to hold computed chunk data before accumulating
            cov_data = {}

            # ---------------------------------------------------------
            # Read pre-opened single-band covariates
            # ---------------------------------------------------------
            for name, (src_h, vrt_h) in single_band_vrts.items():
                cov_data[name] = vrt_h.read(1, window=vrt_h.window(left, bottom, right, top),
                                            out_shape=(dst_height, dst_width)).astype(np.int16)

            # ---------------------------------------------------------
            # Prepare Sentinel-1 block data
            # ---------------------------------------------------------
            s1_stack = {}
            for i, band in enumerate(s1_descriptions, start=1):
                if band:
                    std_name = s1_translation.get(band, band)
                    s1_stack[std_name] = s1_raster.read(i, window=s1_raster.window(left, bottom, right, top),
                                                        out_shape=(dst_height, dst_width))
            for season in ['1', '2', '3']:
                for pol in ['vh', 'vv']:
                    asc_name, desc_name = f's1_{season}_{pol}a', f's1_{season}_{pol}d'
                    if asc_name in s1_stack and desc_name in s1_stack:
                        cov_data[asc_name] = np.where(s1_stack[asc_name] == nodata_value, s1_stack[desc_name],
                                                      s1_stack[asc_name])
                        cov_data[desc_name] = np.where(s1_stack[desc_name] == nodata_value, s1_stack[asc_name],
                                                       s1_stack[desc_name])
                    else:
                        if asc_name in s1_stack: cov_data[asc_name] = s1_stack[asc_name]
                        if desc_name in s1_stack: cov_data[desc_name] = s1_stack[desc_name]

            # ---------------------------------------------------------
            # Prepare Sentinel-2 block data
            # ---------------------------------------------------------
            s2_backup_stack = {}
            for i, band in enumerate(s2_backup_descriptions, start=1):
                if band:
                    std_name = s2_median_translation.get(band, band)
                    s2_backup_stack[std_name] = s2_med_raster.read(i,
                                                                   window=s2_med_raster.window(left,
                                                                                               bottom,
                                                                                               right,
                                                                                               top),
                                                                   out_shape=(dst_height, dst_width))

            for season in range(1, 6):
                s2_stack = {}
                for band in base_s2_bands:
                    name_seasonal = f's2_{season}_{band}'
                    name_backup = f's2_{band}'
                    if name_seasonal in s2_map:
                        s2_data = s2_seas_raster.read(s2_map[name_seasonal],
                                                      window=s2_seas_raster.window(left, bottom, right, top),
                                                      out_shape=(dst_height, dst_width))
                    else:
                        s2_data = np.full((dst_height, dst_width), nodata_value, dtype=np.int16)

                    s2_backup_data = s2_backup_stack.get(name_backup,
                                                         np.full((dst_height, dst_width), nodata_value, dtype=np.int16))
                    s2_filled_data = np.where(s2_data == nodata_value, s2_backup_data, s2_data)

                    s2_stack[band] = s2_filled_data
                    cov_data[name_seasonal] = s2_filled_data

                # Prepare spectral indices
                cov_data[f's2_{season}_nbr'] = calc_normalized_index(s2_stack['nir'], s2_stack['swir2'])
                cov_data[f's2_{season}_ngrdi'] = calc_normalized_index(s2_stack['green'], s2_stack['red'])
                cov_data[f's2_{season}_ndmi'] = calc_normalized_index(s2_stack['nir'], s2_stack['swir1'])
                cov_data[f's2_{season}_ndsi'] = calc_normalized_index(s2_stack['green'], s2_stack['swir1'])
                cov_data[f's2_{season}_ndvi'] = calc_normalized_index(s2_stack['nir'], s2_stack['red'])
                cov_data[f's2_{season}_ndwi'] = calc_normalized_index(s2_stack['green'], s2_stack['nir'])

            # ---------------------------------------------------------
            # Calculate zonal sums and counts for all block data
            # ---------------------------------------------------------
            for name in predictor_all:
                if name in cov_data:
                    # Select block data
                    data = cov_data[name]
                    # Define valid data mask
                    valid_mask = (segment_data > 0) & (data != nodata_value)
                    if segment_nodata is not None:
                        valid_mask &= (segment_data != segment_nodata)
                    # Restrict block data to valid data mask
                    seg_valid = segment_data[valid_mask]
                    data_valid = data[valid_mask]
                    # Calculate sums and counts for blocks that contain valid data
                    if len(seg_valid) > 0:
                        sum_arrays[name] += np.bincount(seg_valid, weights=data_valid, minlength=max_seg_id + 1)
                        count_arrays[name] += np.bincount(seg_valid, minlength=max_seg_id + 1)

            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)

    finally:
        # Close all open single-band VRTs and sources
        for src_h, vrt_h in single_band_vrts.values():
            vrt_h.close()
            src_h.close()

        # Close multi-band VRT handles
        s1_raster.close()
        s2_med_raster.close()
        s2_seas_raster.close()

    # End timing
    end_timing(start_time)

# Calculate block means
print('Calculating zonal means...')
start_time = time.time()
mean_arrays = {}
for name in predictor_all:
    with np.errstate(divide='ignore', invalid='ignore'):
        means = sum_arrays[name] / count_arrays[name]
    means = np.nan_to_num(means, nan=nodata_value)
    mean_arrays[name] = np.round(means).astype(np.int16)
end_timing(start_time)

# Clear aggregation arrays from memory
del sum_arrays, count_arrays

#### WRITE ZONAL RASTER
####____________________________________________________

# Merge zonal means from all blocks to output raster
with rasterio.open(segment_input) as segment_raster:
    print('Merging zonal blocks...')
    start_time = time.time()

    # Define output profile
    output_profile = segment_raster.profile.copy()
    output_profile.update({
        'count': len(predictor_all),
        'dtype': 'int16',
        'nodata': nodata_value,
        'compress': 'lzw',
        'predictor': 2,
        'bigtiff': 'YES',
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512
    })

    # Process output raster
    with rasterio.open(zonal_intermediate, 'w', **output_profile) as dst:
        # Find number of raster blocks
        window_list = []
        for block_index, window in segment_raster.block_windows(1):
            window_list.append(window)

        # Establish raster count
        count = 1
        progress = 0

        # Define band names
        dst.descriptions = tuple(predictor_all)

        # Load segment data
        for block_index, window in segment_raster.block_windows(1):
            segment_data = segment_raster.read(1, window=window)

            # Map invalid segment IDs (e.g. nodata) to 0 safely so they don't break the array index lookup
            safe_segment_data = np.where(segment_data > 0, segment_data, 0)

            # Perform aggregation
            for name, b_idx in band_map.items():
                out_data = mean_arrays[name][safe_segment_data]

                # Define valid mask
                valid_mask = (segment_data > 0)
                if segment_nodata is not None:
                    valid_mask &= (segment_data != segment_nodata)

                # Limit output to valid data
                out_data = np.where(valid_mask, out_data, nodata_value)

                # Write data to output raster
                dst.write(out_data.astype(np.int16), b_idx, window=window)

            # Report progress
            count, progress = raster_block_progress(100, len(window_list), count, progress)

    # End timing
    end_timing(start_time)
    
#### PROCESS CLOUD-OPTIMIZED GEOTIFFS
####____________________________________________________

# Set translation options for GDAL COG driver
cog_options = gdal.TranslateOptions(
    format='COG',
    creationOptions=[
        'COMPRESS=DEFLATE',
        'PREDICTOR=STANDARD',
        'BLOCKSIZE=512',
        'NUM_THREADS=ALL_CPUS',
        'BIGTIFF=YES',
        'RESAMPLING=AVERAGE',
        'OVERVIEW_RESAMPLING=AVERAGE'
    ]
)

# Translate raster to cloud-optimized geotiff
print(f'Creating cloud-optimized geotiff...')
start_time = time.time()
cog_ds = gdal.Translate(zonal_output, zonal_intermediate, options=cog_options)
cog_ds = None
end_timing(start_time)

# Remove intermediate datasets
if os.path.exists(zonal_intermediate):
    os.remove(zonal_intermediate)

# Upload dataset to Google Cloud
print('Uploading final multi-band zonal raster to GCS...')
start_time = time.time()
upload_to_gcs(zonal_output, final_gcs_output, storage_client)
end_timing(start_time)
