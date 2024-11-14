from label_studio_sdk import Client
import rasterio as rio

import geopandas as gpd


API_KEY = ""
ls = Client(url='http://localhost:8080', api_key=API_KEY)
IMAGE_WIDTH = 1000
IMAGE_HEIGHT = 1000


class LabelStudio:
    def __init__(self, base_url='http://localhost:5000'):
        self.base_url = base_url

    def create_review_project(self, client_name, project_title = ""):
        project = ls.create_project(
            title=f'{project_title} {client_name}',
            label_config='''
            <View>
            <Image name="image" value="$image"/>
            <Choices name="review" toName="image">
                <Choice value="correct"/>
                <Choice value="incorrect"/>
            </Choices>
            <PolygonLabels name="label" toName="image">
                        <Label value="Building" background="red"/>
                        <Label value="Tree" background="blue"/>
                </PolygonLabels>
            </View>
            '''
        )
        project_id = project.id
        project_title = project.title
        return project_id, project_title
    
    def create_config(self, config):
        '''
            config in the format: 
                'Choices': ['correct', 'incorrect'],
                'PolygonLabels': ['Building', 'Tree']

        '''
        config_strings = []

        for key, value in config.items():
            # TODO: choices and other label type
            if key == 'PolygonLabels':
                label_string = "\n".join(f""" <Label value="{i}" /> """ for i in value)
                config_string = f'''
                                <PolygonLabels name="label" toName="image">
                                {label_string}
                                </PolygonLabels>
                                '''
                config_strings.append(config_string)
        return f'''
                <View>
                <Image name="image" value="$image"/>
                {"".join(config_strings)}
                </View>
                '''
    
    def create_labeling_project(self, client_name, project_title, config):
        """_summary_

        Args:
            client_name (_type_): _description_
            project_title (_type_): _description_
            config (_type_): format of the config is dict
                Choices': ['correct', 'incorrect'],
                'PolygonLabels': ['Building', 'Tree']


        Returns:
            _type_: _description_
        """
        config_string = self.create_config(config)
        project = ls.create_project(
            title=f'{project_title} {client_name}',
            label_config=config_string
        )
        project_id = project.id
        project_title = project.title
        return project_id, project_title
    
    def import_image_urls(self, project_id, client_name, progress_bar = None):
        image_list = db.fetch_image_list(client_name)
        project = ls.get_project(id=int(project_id))
        for image, width, height in image_list:
            image_path = "s3://en-client-test/" + image
            n_rows = height//IMAGE_HEIGHT
            n_cols = width//IMAGE_WIDTH
            
            raster = rio.open(image_path)
            source_crs = str(raster.crs)
            target_crs = 'EPSG:4326' 
            ctr = 0
            # Import tasks to Label Studio
            for i in range(n_rows):
                for j in range(n_cols):
                    if(progress_bar is not None):
                        progress_bar.progress((i + 1) / n_rows)

                    project.import_tasks([{
                        'data': {"image": f"{self.base_url}/image/{i}/{j}/{image_path[5:]}"}
                    }])
            raster.close()
        print("Imported image URLs to Label Studio.")

    def import_image_urls_and_labels(self, project_id, client_name, progress_bar = None):
        # raster_path = "s3://en-client-test/blue-sky/SK5639.tif"
        image_list = db.fetch_image_list(client_name)
        project = ls.get_project(id=int(project_id))
        for image, width, height in image_list:
            image_path = "s3://en-client-test/" + image
            n_rows = height//IMAGE_HEIGHT
            n_cols = width//IMAGE_WIDTH
            
            raster = rio.open(image_path)
            source_crs = str(raster.crs)
            target_crs = 'EPSG:4326' 
            ctr = 0
            # Import tasks to Label Studio
            for i in range(n_rows):
                for j in range(n_cols):
                    # print("Done")
                    if(progress_bar is not None):
                        progress_bar.progress((i + 1) / n_rows)
                    bbox = get_image_bounds(raster, i, j)
                    bbox = project_geometry(bbox, source_crs)
                    
                    gdf = db.fetch_intersecting_polygons(bbox)
                    gdf = gpd.clip(gdf, bbox)
                    gdf = gdf.to_crs(str(raster.crs))
                    img_transform = get_image_transformation(raster, i, j)
                    gdf['pixel_coords'] = gdf['geometry'].apply(lambda geom: polygon_to_pixel_coords(geom, img_transform))

                    prediction_results = cvt_gpd_to_label_studi_labels(gdf, IMAGE_HEIGHT, IMAGE_WIDTH)
                    prediction = [
                        {
                            "id": ctr,
                            "model_version": "29",
                            "result": prediction_results
                        }
                    ]
                    print(f"{self.base_url}/image/{i}/{j}/{image_path[5:]}")
                    project.import_tasks([{
                        'data': {"image": f"{self.base_url}/image/{i}/{j}/{image_path[5:]}"},
                        'predictions':prediction
                    }])
                    ctr+=1
            raster.close()
        print("Imported image URLs to Label Studio.")
    
    def create_correction_project(self, src_project_id, project_title):
        source_project = ls.get_project(src_project_id)
        tasks_with_predictions = source_project.get_tasks()
        # Import the tasks into the new project
        new_project = ls.start_project(
            title=project_title,
            label_config='''
            <View>
            <Image name="image" value="$image"/>
            <PolygonLabels name="label" toName="image">
                        <Label value="Building" background="red"/>
                        <Label value="Tree" background="blue"/>
                </PolygonLabels>
            </View>
            '''
        )


        tasks_for_import = []
        for task in tasks_with_predictions:
            if(has_incorrect_review_annotation(task)):
                task_for_import = {
                    "data": task['data'],  # Copy task data
                    "annotations": convert_predictions_to_annotations(task)  # Add annotations from predictions
                }
                tasks_for_import.append(task_for_import)
        new_project.import_tasks(tasks_for_import)
       