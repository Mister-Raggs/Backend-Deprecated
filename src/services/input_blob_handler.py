"""
input_blob handler module for processing the blobs that are present in Validation-Successful Folder in Azure Blob Storage
"""
import logging
from datetime import datetime, timedelta
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions

from common import constants, utils, config_reader
from services.input_blob_analysis_service import analyze_blob
from models.input_blob_model import InputBlob, LifecycleStatus, LifecycleStatusTypes
from common.custom_exceptions import (
    MissingConfigException,
    CitadelIDPBackendException,
)


def handle_input_blob_process() -> list[InputBlob]:
    """
    handle_input_blob_process handles the processing of input blobs.

    Returns:
        list[InputBlob]: A list of InputBlob objects that have been processed.

    """

    blob_service_client = utils.get_azure_storage_blob_service_client()

    # Fetching list of input_blobs from mongodb that are to be processed.
    input_blob_list: list[InputBlob] = InputBlob.objects(is_validation_successful=True, is_processing_for_data=False)
    logging.info("Number of input_blobs found in mongodb for processing: %s", len(input_blob_list))

    if config_reader.config_data.has_option("Main", "use-azure-form-recognizer"):
        use_azure_form_recognizer = config_reader.config_data.getboolean("Main", "use-azure-form-recognizer")
    else:
        use_azure_form_recognizer = True

    is_error: bool = True
    for input_blob in input_blob_list:
        try:
            logging.info("Started processing for blob: '%s' ....", input_blob.validation_successful_blob_path)
            set_blob_for_processing_and_update_mongodb(input_blob, blob_service_client)

            if use_azure_form_recognizer:
                logging.info("Starting analysis for blob '%s' ....", input_blob.in_progress_blob_path)
                analyze_blob(input_blob, blob_service_client)
                logging.info("Analysis completed successfully for blob '%s' ....", input_blob.in_progress_blob_path)
                is_error = False

            else:
                logging.info(
                    "Cannot start analysis for blob '%s' since form-recognizer has been disabled",
                    input_blob.in_progress_blob_path,
                )

            input_blob.is_processed_for_data = True

            # Updating Lifecycle Status
            processed_lifecycle_status = LifecycleStatus(
                status=LifecycleStatusTypes.PROCESSED,
                message="Blob processed successfully",
                updated_date_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            input_blob.lifecycle_status_list.append(processed_lifecycle_status)

            input_blob.save()

            set_processing_status_and_move_completed_blobs(blob_service_client, input_blob, is_error)

        except MissingConfigException:
            logging.exception(
                "A Missing Config error occurred while analyzing the input_blob '%s'.",
                input_blob.in_progress_blob_path,
            )

            input_blob.is_processed_for_data = True

            # Updating Lifecycle Status
            processed_lifecycle_status = LifecycleStatus(
                status=LifecycleStatusTypes.PROCESSED,
                message="Blob processed successfully",
                updated_date_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            input_blob.lifecycle_status_list.append(processed_lifecycle_status)

            input_blob.save()

            set_processing_status_and_move_completed_blobs(blob_service_client, input_blob, is_error)

        except CitadelIDPBackendException:
            logging.exception(
                "A General Citadel IDP processing error occured while analyzing the document '%s'.",
                input_blob.in_progress_blob_path,
            )

            # Updating Lifecycle Status
            input_blob.is_processed_for_data = True
            processed_lifecycle_status = LifecycleStatus(
                status=LifecycleStatusTypes.PROCESSED,
                message="Blob processed successfully",
                updated_date_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            input_blob.lifecycle_status_list.append(processed_lifecycle_status)

            input_blob.save()

            set_processing_status_and_move_completed_blobs(blob_service_client, input_blob, is_error)

        except Exception:
            logging.exception(
                "An error occurred while analyzing the input_blob '%s'.", input_blob.in_progress_blob_path
            )

            input_blob.is_processed_for_data = True

            # Updating Lifecycle Status
            processed_lifecycle_status = LifecycleStatus(
                status=LifecycleStatusTypes.PROCESSED,
                message="Blob processed successfully",
                updated_date_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            input_blob.lifecycle_status_list.append(processed_lifecycle_status)

            input_blob.save()

            set_processing_status_and_move_completed_blobs(blob_service_client, input_blob, is_error)

    return input_blob_list


def set_blob_for_processing_and_update_mongodb(input_blob: InputBlob, blob_service_client: BlobServiceClient):
    """
    set_blob_for_processing_and_update_mongodb sets the blob for processing and updates the MongoDB record.

    Args:
        input_blob (InputBlob): The InputBlob object to be processed.
        blob_service_client (BlobServiceClient): The Azure Blob Service client.

    """

    # Updating Lifecycle Status
    processing_lifecycle_status = LifecycleStatus(
        status=LifecycleStatusTypes.PROCESSING,
        message="Starting blob process",
        updated_date_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    input_blob.lifecycle_status_list.append(processing_lifecycle_status)

    input_blob.blob_type, input_blob.form_recognizer_model_id = utils.get_document_type_from_file_name(
        input_blob.validation_successful_blob_path
    )

    input_blob.in_progress_blob_path = input_blob.validation_successful_blob_path.replace(
        constants.VALIDATION_SUCCESSFUL_SUBFOLDER, constants.INPROGRESS_SUBFOLDER
    )

    input_blob.save()

    logging.info(
        "Moving Blob: '%s' to Inprogress folder in Azure-Blob-Storage.",
        input_blob.validation_successful_blob_path,
    )
    move_blob_from_source_folder_to_destination_folder_in_azure_blob_storage(
        blob_service_client, input_blob.validation_successful_blob_path, input_blob.in_progress_blob_path
    )
    logging.info("Blob moved successfuly.")

    input_blob.is_processing_for_data = True

    # Generating sas_url for blob
    input_blob.in_progress_blob_sas_url = get_sas_url(input_blob.in_progress_blob_path, blob_service_client)

    input_blob.save()


def move_blob_from_source_folder_to_destination_folder_in_azure_blob_storage(
    blob_service_client: BlobServiceClient, source_blob_path: str, destination_blob_path: str
):
    """
    move_blob_from_source_folder_to_destination_folder_in_azure_blob_storage moves a blob from a source folder to a destination folder in Azure Blob Storage.

    Args:
        blob_service_client (BlobServiceClient): The Azure Blob Service client.
        source_blob_path (str): The path of the source blob.
        destination_blob_path (str): The path of the destination blob.

    """

    source_blob_client = blob_service_client.get_blob_client(
        container=constants.DEFAULT_BLOB_CONTAINER, blob=source_blob_path
    )

    destination_blob_client = blob_service_client.get_blob_client(
        container=constants.DEFAULT_BLOB_CONTAINER, blob=destination_blob_path
    )

    destination_blob_client.start_copy_from_url(source_blob_client.url)
    source_blob_client.delete_blob()


def get_sas_url(blob_path: str, blob_service_client: BlobServiceClient) -> str:
    """
    get_sas_url generates a shared access signature (SAS) URL for a blob.

    Args:
        blob_path (str): The path of the blob.
        blob_service_client (BlobServiceClient): The Azure Blob Service client.

    Returns:
        str: The SAS URL for the blob.

    """

    account_name = blob_service_client.get_container_client(constants.DEFAULT_BLOB_CONTAINER).account_name

    sas_token = generate_blob_sas(
        account_name,
        constants.DEFAULT_BLOB_CONTAINER,
        blob_path,
        account_key=blob_service_client.credential.account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(hours=1),
    )

    # Constructing the full SAS URL for the blob
    sas_url = f"https://{account_name}.blob.core.windows.net/{constants.DEFAULT_BLOB_CONTAINER}/{blob_path}?{sas_token}"

    return sas_url


def set_processing_status_and_move_completed_blobs(
    blob_service_client: BlobServiceClient, input_blob: InputBlob, is_error: bool
):
    """
    set_processing_status_and_move_completed_blobs sets the processing status and moves completed blobs to their respective folders in Azure Blob Storage.

    Args:
        blob_service_client (BlobServiceClient): The Azure Blob Service client.
        input_blob (InputBlob): The InputBlob object being processed.
        is_error (bool): Indicates whether an error occurred during processing.

    """

    if is_error:
        input_blob.failed_blob_path = input_blob.in_progress_blob_path.replace(
            constants.INPROGRESS_SUBFOLDER, constants.FAILED_SUBFOLDER
        )
        input_blob.save()

        logging.info("Moving Blob: '%s' to Failed folder in Azure-Blob-Storage.", input_blob.in_progress_blob_path)
        move_blob_from_source_folder_to_destination_folder_in_azure_blob_storage(
            blob_service_client, input_blob.in_progress_blob_path, input_blob.failed_blob_path
        )
        logging.info("Blob moved successfuly.")

        input_blob.is_processed_success = False
        input_blob.is_processed_failed = True

        # Updating Lifecycle Status
        processed_and_failed_lifecycle_status = LifecycleStatus(
            status=LifecycleStatusTypes.FAILED,
            message="Blob moved to Failed folder in Azure-Blob-Storage",
            updated_date_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        input_blob.lifecycle_status_list.append(processed_and_failed_lifecycle_status)

        input_blob.save()

    else:
        input_blob.success_blob_path = input_blob.in_progress_blob_path.replace(
            constants.INPROGRESS_SUBFOLDER, constants.SUCCESSFUL_SUBFOLDER
        )
        input_blob.save()

        logging.info("Moving Blob: '%s' to Successful folder in Azure-Blob-Storage.", input_blob.in_progress_blob_path)
        move_blob_from_source_folder_to_destination_folder_in_azure_blob_storage(
            blob_service_client, input_blob.in_progress_blob_path, input_blob.success_blob_path
        )
        logging.info("Blob moved successfuly.")

        input_blob.is_processed_success = True
        input_blob.is_processed_failed = False

        # Updating Lifecycle Status
        processed_and_success_lifecycle_status = LifecycleStatus(
            status=LifecycleStatusTypes.SUCCESS,
            message="Blob moved to Successful folder in Azure-Blob-Storage",
            updated_date_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        input_blob.lifecycle_status_list.append(processed_and_success_lifecycle_status)

        input_blob.save()
