"""
input_blob_analysis_service blob module for analyzing the blob through form recognizer and storing its result in azure blob storage.     
"""
import json
import os
import logging
from azure.core.credentials import AzureKeyCredential
from azure.core.serialization import AzureJSONEncoder
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.storage.blob import BlobServiceClient, ContentSettings

from models.input_blob_model import InputBlob, ResultJsonMetaData
from common import config_reader, utils, constants
from common.custom_exceptions import (
    MissingConfigException,
    CitadelIDPBackendException,
)


def analyze_blob(input_blob: InputBlob, blob_service_client: BlobServiceClient):
    """
    analyze_blob analyzes the blob using Azure Form Recognizer service and
    stores the resulting analysis as JSON in Azure Blob Storage.

    Args:
        input_blob (InputBlob): An instance of the InputBlob class representing the blob to be analyzed.
        blob_service_client (BlobServiceClient): An instance of the Azure BlobServiceClient for working
            with Azure Blob Storage.

    Raises:
        MissingConfigException: If required configuration values are missing or empty.
        CitadelIDPBackendException: If the input_blob.in_progress_blob_sas_url is empty.
        Exception: Any unhandled exceptions during the process.
    """

    if config_reader.config_data.has_option("Main", "env"):
        env = config_reader.config_data.get("Main", "env")
    else:
        # If 'env' property is missing in config file it is set to local.
        env = "local"

    if env == "prod":
        # If 'env' is 'prod', 'use_azure_form_recognizer' property is taken from config file.
        if config_reader.config_data.has_option("Main", "use-azure-form-recognizer"):
            use_azure_form_recognizer = config_reader.config_data.getboolean("Main", "use-azure-form-recognizer")
        else:
            # If 'use_azure_form_recognizer' property is missing in config file, it is set to False.
            use_azure_form_recognizer = False
    else:
        # If 'env' is not 'prod', 'use_azure_form_recognizer' is set to 'False'.
        use_azure_form_recognizer = False

    logging.info("use_azure_form_recognizer is set as '%s'", use_azure_form_recognizer)
    if use_azure_form_recognizer:
        if not config_reader.config_data.has_option("Main", "form-recognizer-key"):
            raise MissingConfigException("Main.form-recognizer-key is missing in config.")

        form_recognizer_key = config_reader.config_data.get("Main", "form-recognizer-key")
        if not utils.string_is_not_empty(form_recognizer_key):
            raise MissingConfigException("Main.form-recognizer-key is present but has empty value.")

        if not config_reader.config_data.has_option("Main", "form-recognizer-endpoint"):
            raise MissingConfigException("Main.form_recognizer_endpoint is missing in config.")

        form_recognizer_endpoint = config_reader.config_data.get("Main", "form-recognizer-endpoint")
        if not utils.string_is_not_empty(form_recognizer_endpoint):
            raise MissingConfigException("Main.form_recognizer_endpoint is present but has empty value.")

        document_analysis_client = DocumentAnalysisClient(
            form_recognizer_endpoint, credential=AzureKeyCredential(form_recognizer_key)
        )

        poller = None

        if utils.string_is_not_empty(input_blob.in_progress_blob_sas_url):
            poller = document_analysis_client.begin_analyze_document_from_url(
                input_blob.form_recognizer_model_id,
                input_blob.in_progress_blob_sas_url,
            )

        else:
            raise CitadelIDPBackendException("input_blob.in_progress_blob_sas_url should be non empty.")

        # Waiting for the analysis to complete and getting the result
        result = poller.result()

        # Converting the result to a dictionary
        result_dict = [result.to_dict()]

    else:
        result_dict = "No result is generated because Form Recognizer is Disabled"

    # Creating a dictionary with the blob name and blob output data
    final_result = {
        "input_file_name": os.path.basename(input_blob.in_progress_blob_path),
        "recognizer_result_data": result_dict,
    }

    # Serializing the final result to JSON
    result_json = json.dumps(final_result, cls=AzureJSONEncoder)

    # Defining the path where the JSON output will be stored in Azure Blob Storage
    path = input_blob.in_progress_blob_path.replace("/Inprogress/", "/")
    result_json_path_in_azure_blob_storage = (
        f"{os.path.dirname(path)}/{os.path.splitext(os.path.basename(path))[0]}.json"
    )

    # Getting a BlobClient for uploading the JSON result
    blob_client = blob_service_client.get_blob_client(
        container=constants.DEFAULT_RESULT_JSON_CONTAINER, blob=result_json_path_in_azure_blob_storage
    )

    # Uploading the JSON result to Azure Blob Storage and updating Mongodb
    try:
        blob_client.upload_blob(
            result_json, overwrite=False, content_settings=ContentSettings(content_type="application/json")
        )
        logging.info("Uploaded result_json file to Azure-Blob-Storage")
        input_blob.json_output = ResultJsonMetaData(
            json_result_container_name=constants.DEFAULT_RESULT_JSON_CONTAINER,
            json_result_blob_path=result_json_path_in_azure_blob_storage,
        )

        input_blob.save()

    except:
        logging.exception("Failed to upload json result of blob '%s' to blob storage", input_blob.in_progress_blob_path)
