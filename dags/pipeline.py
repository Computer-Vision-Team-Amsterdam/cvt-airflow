import os
from datetime import timedelta
from typing import Final, Optional
from airflow.utils.dates import days_ago

from airflow import DAG
from airflow.operators.python_operator import PythonOperator
from airflow.providers.cncf.kubernetes.operators.kubernetes_pod import (
    KubernetesPodOperator,
)

from azure.storage.blob import BlobServiceClient
from azure.identity import ManagedIdentityCredential


# [registry]/[imagename]:[tag]
RETRIEVAL_CONTAINER_IMAGE: Optional[str] = 'cvtweuacrogidgmnhwma3zq.azurecr.io/retrieve:latest'
BLUR_CONTAINER_IMAGE: Optional[str] = 'cvtweuacrogidgmnhwma3zq.azurecr.io/blur:latest'
METADATA_CONTAINER_IMAGE: Optional[str] = 'cvtweuacrogidgmnhwma3zq.azurecr.io/store_metadata:latest'
DETECT_CONTAINER_IMAGE: Optional[str] = 'cvtweuacrogidgmnhwma3zq.azurecr.io/detection:latest'

date = '{{dag_run.conf["date"]}}'  # set in config when triggering DAG

# Command that you want to run on container start
DAG_ID: Final = "cvt-pipeline"
DATATEAM_OWNER: Final = "cvision2"
DAG_LABEL: Final = {"team_name": DATATEAM_OWNER}
AKS_NAMESPACE: Final = os.getenv("AIRFLOW__KUBERNETES__NAMESPACE")
AKS_NODE_POOL: Final = "cvision2work"

# List here all environment variables that also needs to be
# used inside the K8PodOperator pod.
GENERIC_VARS_NAMES: list = [
    "USER_ASSIGNED_MANAGED_IDENTITY",
    "AIRFLOW__SECRETS__BACKEND_KWARGS",
    "AIRFLOW_CONN_POSTGRES_DEFAULT"
]


client_id = os.getenv("USER_ASSIGNED_MANAGED_IDENTITY")
credential = ManagedIdentityCredential(client_id=client_id)
blob_service_client = BlobServiceClient(account_url="https://cvtdataweuogidgmnhwma3zq.blob.core.windows.net",
                                       credential=credential)


def get_generic_vars() -> dict[str, str]:
    """Get generic environment variables all containers will need.

    Note: The K8PodOperator spins up a new node. This node needs
        to be fed with the nessacery env vars. Its not inheriting
        it from his big brother/sister/neutral the worker pod.

    :returns: All (generic) environment variables that need to be included into the container.
    """
    GENERIC_VARS_DICT: dict[str, str] = {
        variable: os.environ[variable] for variable in GENERIC_VARS_NAMES
    }
    return GENERIC_VARS_DICT


def remove_unblurred_images():
    """
    Remove unblurred images from storage account after we:
    - blurred them
    - stored the metadata in the postgres database
    """

    # Get the blob client to be deleted
    todelete_blob_client = blob_service_client.get_blob_client(container="unblurred", blob=f"{date}")

    try:
        # Check if the blob exists
        if todelete_blob_client.exists():
            # Delete blob
            todelete_blob_client.delete_blob()
            print("Blob deleted successfully!")
        else:
            print("Blob does not exist!")

    except Exception as e:
        print("Failed to delete blob. Error:" + str(e))


with DAG(
        DAG_ID,
        description="test-dag",
        default_args={
            'depends_on_past': False,
            'email': ['airflow@example.com'],
            'email_on_failure': False,
            'email_on_retry': False,
            'retries': 1,
            'retry_delay': timedelta(minutes=5),
            'start_date': days_ago(1),
        },
        template_searchpath=["/"],
        catchup=False,
) as dag:
    """
    retrieve_images = KubernetesPodOperator(
            task_id='retrieve_images',
            namespace=AKS_NAMESPACE,
            image=RETRIEVAL_CONTAINER_IMAGE,
            # beware! If env vars are needed from worker,
            # add them here.
            env_vars=get_generic_vars(),
            cmds=["python"],
            arguments=["/opt/retrieve_images.py", "--date", date],
            labels=DAG_LABEL,
            name=DAG_ID,
            # Determines when to pull a fresh image, if 'IfNotPresent' will cause
            # the Kubelet to skip pulling an image if it already exists. If you
            # want to always pull a new image, set it to 'Always'.
            image_pull_policy="Always",
            # Known issue in the KubernetesPodOperator
            # https://stackoverflow.com/questions/55176707/airflow-worker-connection-broken-incompleteread0-bytes-read
            # set get_logs to false
            # If true, logs stdout output of container. Defaults to True.
            get_logs=True,
            in_cluster=True,  # if true uses our service account token as aviable in Airflow on K8
            is_delete_operator_pod=False,  # if true delete pod when pod reaches its final state.
            log_events_on_failure=True,  # if true log the pod’s events if a failure occurs
            hostnetwork=True,  # If True enable host networking on the pod. Beware, this value must be
            # set to true if you want to make use of the pod-identity facilities like managed identity.
            reattach_on_restart=True,
            dag=dag,
            # Timeout to start up the Pod, default is 120.
            startup_timeout_seconds=3600,
            # to prevent tasks becoming marked as failed when taking longer
            # and deleting them if staling
            execution_timeout=timedelta(hours=4),
            # Select a specific nodepool to use. Could also be specified by nodeAffinity.
            node_selector={"nodetype": AKS_NODE_POOL},
            # List of Volume objects to pass to the Pod.
            volumes=[],
            # List of VolumeMount objects to pass to the Pod.
            volume_mounts=[],
        )

    blur_images = KubernetesPodOperator(
        task_id='blur_images',
        namespace=AKS_NAMESPACE,
        image=BLUR_CONTAINER_IMAGE,
        env_vars=get_generic_vars(),
        cmds=["python"],
        arguments=["/app/blur.py",  "--date", date],
        labels=DAG_LABEL,
        name=DAG_ID,
        image_pull_policy="Always",
        get_logs=True,
        in_cluster=True,
        is_delete_operator_pod=False, 
        log_events_on_failure=True, 
        hostnetwork=True, 
        reattach_on_restart=True,
        dag=dag,
        startup_timeout_seconds=3600,
        execution_timeout=timedelta(hours=4),
        node_selector={"nodetype": AKS_NODE_POOL},
        volumes=[],
        volume_mounts=[],
    )

    store_images_metadata = KubernetesPodOperator(
        task_id='store_images_metadata',
        namespace=AKS_NAMESPACE,
        image=METADATA_CONTAINER_IMAGE,
        env_vars=get_generic_vars(),
        cmds=["python"],
        arguments=["/opt/metadata_to_postgresql.py", "--date", date],
        labels=DAG_LABEL,
        name=DAG_ID,
        image_pull_policy="Always",
        get_logs=True,
        in_cluster=True,
        is_delete_operator_pod=False,
        log_events_on_failure=True,
        hostnetwork=True,
        reattach_on_restart=True,
        dag=dag,
        startup_timeout_seconds=3600,
        execution_timeout=timedelta(hours=4),
        node_selector={"nodetype": AKS_NODE_POOL},
        volumes=[],
        volume_mounts=[],
    )

    remove_unblurred_images = PythonOperator(
        task_id='remove_unblurred_images',
        python_callable=remove_unblurred_images,
        provide_context=True,
        dag=dag)

    detect_containers = KubernetesPodOperator(
        task_id='detect_containers',
        namespace=AKS_NAMESPACE,
        image=DETECT_CONTAINER_IMAGE,
        env_vars=get_generic_vars(),
        cmds=["python"],
        arguments=["/app/inference.py",
                   "--subset", date,
                   "--device", "cpu",
                   "--data_folder", "blurred",
                   "--weights", "model_final.pth",
                   "--output_path", "outputs"],
        labels=DAG_LABEL,
        name=DAG_ID,
        image_pull_policy="Always",
        get_logs=True,
        in_cluster=True,
        is_delete_operator_pod=False,
        log_events_on_failure=True,
        hostnetwork=True,
        reattach_on_restart=True,
        dag=dag,
        startup_timeout_seconds=3600,
        execution_timeout=timedelta(hours=4),
        node_selector={"nodetype": AKS_NODE_POOL},
        volumes=[],
        volume_mounts=[],
    )
    """
    remove_unblurred_images = PythonOperator(
        task_id='remove_unblurred_images',
        python_callable=remove_unblurred_images,
        provide_context=True,
        dag=dag)

# FLOW

    #flow = retrieve_images >> [blur_images, store_images_metadata] >> remove_unblurred_images >> detect_containers
    flow = remove_unblurred_images


