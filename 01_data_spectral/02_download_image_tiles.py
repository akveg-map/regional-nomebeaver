# ---------------------------------------------------------------------------
# Download image tiles
# Author: Timm Nawrocki, Alaska Center for Conservation Science
# Last Updated: 2026-10-15
# Usage: Must be executed in a Python 3.12+ installation.
# Description: 'Download image tiles' downloads individual tiles from the Vantor Vivid 2023 composite based on spatial match with a pre-configured set of download grids.
# ---------------------------------------------------------------------------

# Import packages
import os
import time
import requests
import geopandas as gpd
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from akutils import *

#### SET UP DIRECTORIES, FILES, AND FIELDS
####____________________________________________________

# Set root directory
drive = '/home'
root_folder = 'twnawrocki'

# Define folder structure
region_geopackage = os.path.join(drive, root_folder, 'regional_nomebeaver/region_data/region_data_3338.gpkg')
output_folder = os.path.join(drive, root_folder, 'regional_nomebeaver/image_data/tiles')

# Define input file
grid_layer = 'tiles_001_3338'

# Set desired output resolution in meters
resolution_m = 2.0

# Define image service url
base_url = 'https://apps.geo.fpac.usda.gov/nrcs-imagery/rest/services/ortho_imagery/alaska_vivid_2023_30cm/ImageServer'
export_url = f'{base_url}/exportImage'

#### PROCESSING SCRIPT
####____________________________________________________

# Identify naming column
name_col = 'grid_code'

# Load the grid shapefile
grid_data = gpd.read_file(region_geopackage, layer=grid_layer)

# Optional row filtering
#target_grids = ['C280R014']
#grid_data = grid_data[grid_data[name_col].isin(target_grids)].reset_index(drop=True)

# Calculate number of grids to process
grid_count = len(grid_data)
print(f'Found {grid_count} grid cells to process.')

# Iterate through each grid cell and export imagery
for idx, row in grid_data.iterrows():
    # Define output file
    image_output = os.path.join(output_folder, f'{row[name_col]}.tif')

    # Export image if it does not already exist in GCS
    if not os.path.exists(image_output):
        print(f'Processing grid {idx + 1} of {grid_count}...')
        start_time = time.time()

        # Extract exact bounds of the current grid cell and round to 2 decimal places
        xmin, ymin, xmax, ymax = row.geometry.bounds
        xmin, ymin, xmax, ymax = round(xmin, 2), round(ymin, 2), round(xmax, 2), round(ymax, 2)

        # Dynamically calculate the pixels needed based on the grid cell's exact dimensions
        img_width = max(1, int(round((xmax - xmin) / resolution_m)))
        img_height = max(1, int(round((ymax - ymin) / resolution_m)))

        export_params = {
            'f': 'image',
            'bbox': f'{xmin},{ymin},{xmax},{ymax}',
            'bboxSR': '3338',
            'imageSR': '3338',
            'format': 'tiff',
            'size': f'{img_width},{img_height}',
            'interpolation': 'RSP_BilinearInterpolation'
        }

        try:
            # Request the image from the server
            export_response = requests.post(export_url, data=export_params, stream=True)

            # Handle server errors
            if export_response.status_code == 400:
                print(f'\tGrid cell is empty or rejected by server (400 Error).')
                continue
            export_response.raise_for_status()

            # Parse JSON error messages
            content_type = export_response.headers.get('Content-Type', '')
            if 'json' in content_type or 'text' in content_type:
                error_msg = export_response.json()
                print(f'\tERROR: {error_msg}')
                continue

            # Stream the image straight to the hard drive
            print(f'\tStreaming directly to disk...')
            with open(image_output, 'wb') as f:
                for chunk in export_response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

            # Assign spatial reference to the downloaded TIFF using calculated dimensions
            with rasterio.open(image_output, 'r+') as dataset:
                dataset.crs = CRS.from_epsg(3338)
                dataset.transform = from_bounds(
                    xmin, ymin,
                    xmax, ymax,
                    img_width, img_height
                )
            print(f'\tSaved and georeferenced: {row[name_col]}.tif')

        # Catch additional errors
        except Exception as e:
            print(f'  [Failed] Could not process {row[name_col]}: {e}')
            time.sleep(1)

        # Provide a pause for the server
        end_timing(start_time)
        time.sleep(1)

    # Print message for existing grid
    else:
        print(f'Grid {idx + 1} of {grid_count} already processed.')

print('All grid downloads complete.')
