import os
from datetime import timedelta, datetime
from typing import Final
import requests
from airflow import DAG
from airflow.providers.cncf.kubernetes.operators.kubernetes_pod import (
   KubernetesPodOperator,
)
from environment import RETRIEVAL_CONTAINER_IMAGE


def test():
   response = requests.get("https://api.data.amsterdam.nl/panorama/panoramas/?limit_results=1")
   try:
      response.raise_for_status()
   except Exception as e:
      print(e)
      raise e
   print(response.content)


default_args = {
   'depends_on_past': False,
   'email': ['airflow@example.com'],
   'email_on_failure': False,
   'email_on_retry': False,
   'retries': 0,
   'retry_delay': timedelta(minutes=5),
}

DAG_ID: Final = "cvt-pipeline-small_multiprocessing"
DATATEAM_OWNER: Final = "cvision2"
DAG_LABEL: Final = {"team_name": DATATEAM_OWNER}
AKS_NAMESPACE: Final = os.getenv("AIRFLOW__KUBERNETES__NAMESPACE")
AKS_NODE_POOL: Final = "cvision2work"

def get_generic_vars() -> dict[str, str]:
   """Get generic environment variables all containers will need.

   Note: The K8PodOperator spins up a new node. This node needs
       to be fed with the nessacery env vars. Its not inheriting
       it from his big brother/sister/neutral the worker pod.

   :returns: All (generic) environment variables that need to be included into the container.
   """
   GENERIC_VARS_NAMES: list = [
      "USER_ASSIGNED_MANAGED_IDENTITY",
      "AIRFLOW__SECRETS__BACKEND_KWARGS",
      "AIRFLOW_CONN_POSTGRES_DEFAULT"
   ]
   GENERIC_VARS_DICT: dict[str, str] = {
      variable: os.environ[variable] for variable in GENERIC_VARS_NAMES
   }
   return GENERIC_VARS_DICT


with DAG(
        "api_test",
        start_date=datetime(2023, 1, 1),
        max_active_runs=5,
        schedule_interval="*/2 * * * *",
        default_args=default_args,
        catchup=False
) as dag:
   retrieve_images = KubernetesPodOperator(
      task_id='api_test',
      namespace=AKS_NAMESPACE,
      image=RETRIEVAL_CONTAINER_IMAGE,
      # beware! If env vars are needed from worker,
      # add them here.
      env_vars=get_generic_vars(),
      cmds=["python3 -c \"import requests; print(try: requests.get('https://api.data.amsterdam.nl/panorama/panoramas/?limit_results=1').raise_for_status(); except Exception as e: print(e); raise e)\""],
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
      is_delete_operator_pod=True,  # if true delete pod when pod reaches its final state.
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
