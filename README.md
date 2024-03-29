# Airflow-computervision
This is the airflow repository of the computer vision team.
This repository contains the pipelines that are used in our container project.
Some more notes about docker and kubernetes can be found in our [wiki](https://cvteamamsterdam.atlassian.net/wiki/spaces/CVT/pages/24248321/Technical+documentation+of+the+project+illegal+containers+in+Amsterdam).

We created the pipelines in this repository based on the below image in the [CVT Drafts Miro board](https://miro.com/app/board/uXjVOVQfTW4=/?share_link_id=412250854483).

## Structure

As you can see in the image below our pipeline is split in three main parts.
<img src="docs/images/miro-pipeline-overview.png">


1. DAG 1. Processing.

<img src="docs/images/miro-pipeline-dag-1.png" width="800">

This DAG is responsible for retrieving images from cloud, storing them in our storage account from Azure 
and running 2 AI models, the blurring model and the container detection model. 
It also contains tasks to remove the images from the storage account once they're processed. 
This first DAG is going to be run multiple times in order to optimise the large amount of data that must be processed.


2. DAG 2. Postprocessing.

<img src="docs/images/miro-pipeline-dag-2.png" width="800">

This DAG contains only one task end is responsible for combining the predictions of the container model with 
two other sources namely the permit data from Decos and the locations of vulnerable bridges. 
This pipeline also creates the maps in HTML format which summarise the current situation of where illegal containers 
are present in the city centre.


3. DAG 3. Submit notifications.

<img src="docs/images/miro-pipeline-dag-3.png" width="600">

This DAG is responsible for sending a signal to see you based on the content of the maps produced by DAG 2. 

## How to trigger a DAG.

Each DAG is triggered manually from airflow. When we trigger one pipeline we trigger it with a configuration.

<img src="docs/images/trigger-pipeline-1.png" width="800">

In the configuration JSON, fill in the date argument in the `%Y-%m-%d %H:%M:%S.%f` format, as shown below.

Lastly, press the `Trigger` button.

<img src="docs/images/trigger-pipeline-2.png" width="800">

## Where we store results
While the DAGs are running, the data (images, json files, csv files) are being created in different containers
in the storage account. Below is an overview of the containers in `development` storage account.
<img src="docs/images/azure-containers.png" width="800">
The purpose of the containers is as follows:
- `retrieve-images-input`: We run the pipeline on day X. Thus, we need to download all images from CloudVPS from day X.
This container has a list of files with panorama ids that should be downloaded. There are multiple files because we split
the workload among multiple workers, given the large amount images to download. (~10k per day)
- `unblurred`: This is where we store the downloaded images. These are "badly" blurred images from the 
datapunt objectstore.
- `blurred`: This is where we store the blurred images after the `Blur` task from DAG 1.

**NOTE:** After this task successfully finishes, the corresponding "badly" blurred images from the `unblurred` container
are removed.
- `detections`: This is where we store the output of the `Detect Containers` task from DAG 1. The output is a 
`coco_instances_results_*.json` file with ids of images that have containers and a `empty_predictions.json` file
with ids of images that do not have containers.

**NOTE:** After this task successfully finishes, based on the `empty_predictions.json` file, the corresponding images 
from the `blurred` container are removed.
- `postprocessing-input`: This is where we store the input of DAG 2, namely the `coco_instances_results_combined.json`
file, the daily Decos dump and the general `vulnerable_bridges.geojson` file.
- `post-processing-output`: This is where we store the output of DAG 2, namely the `Overview.html` and
`Prioritized.html` maps, the `prioritized_objects.csv` (both maps are created based on this file) and the 
`permit_locations_failed.csv` file.

## Workflow

Let's work with one example.

The car is collecting images in the interval 09:00-15:00 on a Monday, 2nd of January 2023.

The date of the mission is thus `2023-01-02`. The mission is split in 2 or 3 sessions. After each session, 
the process of uploading the images to CloudVPS starts and images are one by one available to us.


In other words, these images are available to download later on that day on Monday, or it may take longer, until
3rd of January. This is irrelevant, the mission date is still `2023-01-02` and the DAGS will be triggered
with this date!

Let's assume the following scenario:
- by 15:00 PM on Monday 2nd of January 2023, the first 20% of images are uploaded to CloudVPS. 

This is the time to trigger DAG 1 and process these available images.

We trigger DAG 1 with `{"date":"2023-01-02 15:00:00.00"}`. We choose this timestamp since it makes sense with this 
example, it does not have to correspond with the precise current time, as long as we all agree on this.

- by 20:00 PM on Monday 2nd of January 2023, the next 50% of images are uploaded to CloudVPS.

This is the time to trigger DAG 1 again and process the newly available images.

We trigger DAG 1 with `{"date":"2023-01-02 20:00:00.00"}`.

- by 20:00 PM on **Tuesday 3rd** of January 2023, the last 30% of images are uploaded to CloudVPS.

Even if it's one day later, we must tell the DAG that this data actually belongs to the mission from the day before, 
so we **still trigger DAG 1 with the date of 2nd of January 2023**. Now, as for the precise timestamp, we can agree it 
should be after the last available timestamp, which is `{"date":"2023-01-02 20:00:00.00"}`. Thus, we trigger 
DAG 1 with `{"date":"2023-01-02 21:00:00.00"}`


Now that we processed all images, it is time to trigger DAG 2. Let's assume it is now 22:00 PM on Tuesday 3rd of 
January 2023.
Again, same as explained before, we must tell DAG 2 that this data actually belongs to the mission from the day 
before, so we trigger DAG 2 with the date of 2nd of January 2023. The precise timestamp can be anything, since we only
use the date from now onwards. (We assume we only trigger DAG 2 once per mission). Thus, we trigger DAG 2 with 
`{"date":"2023-01-02 21:00:00.00"}`.

The same holds for DAG 3. Again, we trigger it with the date of 2nd of January. Again, the
timestamp is irrelevant, we only care about the date. Thus, we trigger DAG 2 with 
`{"date":"2023-01-02 21:00:00.00"}`.

## Failed DAGs

Let's assume one DAG in the example above fail. In this case, Airflow allows us to resume the DAG from the task 
that failed. We also need to remove any present "bad" output created by the failed task. 
For example, if the `Detect Containers` task in DAG 1 failed when triggered `{"date":"2023-01-02 20:00:00.00"}`, 
then we delete the `detections/2023-01-02 20:00:00.00` container from the storage account, if any. 

In the image below we see that the `store_image_metadata` task has failed. 
<img src="docs/images/airflow-resume-failed-task-1.png" width="800">

To re-run this task, we click on it, then on the `Clear` button.
<img src="docs/images/airflow-resume-failed-task-2.png" width="800">
