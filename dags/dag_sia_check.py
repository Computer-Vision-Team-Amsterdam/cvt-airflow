import json
import os
from datetime import timedelta
import shutil
import socket
from datetime import datetime
from pathlib import Path
from typing import Final, Optional, Tuple
from airflow.utils.dates import days_ago

import requests
from requests.auth import HTTPBasicAuth
from azure.identity import ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient

from airflow import DAG
from airflow.operators.python_operator import PythonOperator

# Command that you want to run on container start
DAG_ID: Final = "sia"
DATATEAM_OWNER: Final = "cvision2"
DAG_LABEL: Final = {"team_name": DATATEAM_OWNER}
AKS_NAMESPACE: Final = os.getenv("AIRFLOW__KUBERNETES__NAMESPACE")
AKS_NODE_POOL: Final = "cvision2work"


client_id = os.getenv("USER_ASSIGNED_MANAGED_IDENTITY")
credential = ManagedIdentityCredential(client_id=client_id)

airflow_secrets = json.loads(os.environ["AIRFLOW__SECRETS__BACKEND_KWARGS"])
KVUri = airflow_secrets["vault_url"]

client = SecretClient(vault_url=KVUri, credential=credential)
sia_password = client.get_secret(name="sia-password-acc")
socket.setdefaulttimeout(100)


def check_sia_connection():
    data = {
        'grant_type': 'client_credentials',
        'client_id': 'sia-cvt',
        'client_secret': f'{sia_password.value}',
    }

    print(data)
    tokenURL = 'https://iam.amsterdam.nl/auth/realms/datapunt-ad-acc/protocol/openid-connect/token'
    response = requests.post(tokenURL, data=data)

    if response.status_code == 200:
        token = response.json()["access_token"]
        url = "https://acc.api.data.amsterdam.nl/signals/v1/private/signals"
        headers = {'Authorization': "Bearer {}".format(token)}
        response = requests.get(url, headers=headers)
        print(f"Respose status SIA private endpoint: {response.status_code}.")
    else:
        print(f"Response status code for token {response.status_code}")

with DAG(
    DAG_ID,
    description="Dag to check individual containers before adding them into the pipeline",
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

    test_sia = PythonOperator(task_id='test_sia',
                              python_callable=check_sia_connection,
                              provide_context=True,
                              dag=dag)


# FLOW
var = (
        test_sia
)
