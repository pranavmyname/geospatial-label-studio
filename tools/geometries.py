from rasterio.windows import Window
from shapely.geometry import box, Polygon
from pyproj import Transformer
import rasterio as rio
from shapely.geometry import box, Polygon, MultiPolygon, GeometryCollection, LineString
from rasterio.transform import rowcol

IMAGE_WIDTH = 1000
IMAGE_HEIGHT = 1000

def project_geometry(geometry, source_crs, target_crs = 'EPSG:4326'):
    # Apply transformation to each coordinate in the geometry
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    return Polygon([transformer.transform(x, y) for x, y in geometry.exterior.coords])

def has_incorrect_review_annotation(task):
    for annotation in task.get('annotations', []):
        for result in annotation.get('result', []):
            if result.get('from_name') == 'review' and result.get('value', {}).get('text') == ['incorrect']:
                return True
    return False

def convert_predictions_to_annotations(task):
    annotations = []
    for prediction in task['annotations']:
        if(len(prediction['result'])>0):
            prediction['result'] = dict(map(lambda x: {key: val for key, val in x.items() if key != 'readonly'}, prediction['result']))
        annotation = {
            "result": prediction['result'],  # Copy the prediction result as annotation result
            "completed_by": prediction.get('model_version', 'Auto'),  # Tag with model version
            "was_cancelled": False,
            "ground_truth": False,
        }
        annotations.append(annotation)
    return annotations

def get_image_bounds(raster, row_off, col_off):
    window = Window(col_off*IMAGE_WIDTH,row_off*IMAGE_HEIGHT, IMAGE_WIDTH, IMAGE_HEIGHT)
    # rasterio.windows.bounds
    transform = raster.transform
    bounds = rio.windows.bounds(window, transform)
    return box(*bounds)

def get_image_transformation(raster, row_off, col_off):
    window = Window(col_off*IMAGE_WIDTH,row_off*IMAGE_HEIGHT, IMAGE_WIDTH, IMAGE_HEIGHT)
    transform = raster.transform
    window_transform = rio.windows.transform(window, transform)
    return window_transform

def polygon_to_pixel_coords(geometry, transform):
    if isinstance(geometry, Polygon):  # Check if it's a Polygon
        exterior_coords = list(geometry.exterior.coords)
        pixel_coords = [rowcol(transform, x, y) for x, y in exterior_coords]
        return [pixel_coords]
    elif isinstance(geometry, MultiPolygon):  # Handle MultiPolygon
        all_pixel_coords = []
        for poly in geometry.geoms:
            exterior_coords = list(poly.exterior.coords)
            pixel_coords = [rowcol(transform, x, y) for x, y in exterior_coords]
            all_pixel_coords.append(pixel_coords)
        return all_pixel_coords
    elif isinstance(geometry, GeometryCollection):  # Handle GeometryCollection
        all_pixel_coords = []
        for geom in geometry.geoms:
            if isinstance(geom, Polygon):  # Extract polygons only
                exterior_coords = list(geom.exterior.coords)
                pixel_coords = [rowcol(transform, x, y) for x, y in exterior_coords]
                all_pixel_coords.append(pixel_coords)
        return all_pixel_coords


def create_polygon_result(pixel_coords, original_width, original_height, label, polygon_id):
    # Normalize the pixel coordinates by dividing by the image dimensions
    normalized_coords = [
        [float(x) / original_width * 100.0, float(y) / original_height * 100.0]  # Convert to percentage values
        for (y, x) in pixel_coords  # Notice: (y, x) is the pixel coord (row, col)
    ]
    
    # Create the prediction JSON structure
    polygon_result = {
        "original_width": original_width,
        "original_height": original_height,
        "image_rotation": 0,
        "value": {
            "points": normalized_coords,  # Use normalized coordinates
            "closed": True,
            "polygonlabels": [label]
        },
        "id": polygon_id,
        "from_name": "label",
        "to_name": "image",
        "type": "polygonlabels"
    }
    return polygon_result
    


def cvt_gpd_to_label_studi_labels(gdf, image_height, image_width):
    results = []
    ctr = 0 
    for idx, row in gdf.iterrows():
        # Extract the pixel coordinates for this row
        pixel_coords = row['pixel_coords']  # List of pixel (row, col) coordinates
        label_value = row['label_id']
        if(isinstance(row['geometry'], LineString)): 
            continue
        # pixel_coords = np.clip(np.array(pixel_coords), 50, 900).tolist()
        class_label = 'Tree'
        # if(label_value == 8): class_label = "Building"
        if(label_value == 8): continue
        # Generate a polygon result dictionary
        for pixel_coord in pixel_coords:
            polygon_result = create_polygon_result(
                pixel_coords=pixel_coord,
                original_width=image_width,
                original_height=image_height,
                label=class_label,
                polygon_id=str(ctr)  # Use the index as the ID, or any unique identifier
            )
            
            # Append the polygon result to the overall result list
            results.append(polygon_result)
            ctr+=1


    return results