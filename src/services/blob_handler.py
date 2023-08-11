"""
Blob handler module for reading and writing azure blob storage
"""
import logging

from common import constants, utils
from common.custom_exceptions import (
    FolderMissingBusinessException,
    CitadelIDPProcessingException,
    MissingConfigException,
)

from common.data_objects import InputBlob
from services.document_analysis_service import analyze_blob


def check_and_process_blob_storage() -> list[InputBlob]:
    """
    Checks and processes the azure blob storage.

    Returns:
        list[InputBlob]: List of processed input blobs.
    Raises:
        FolderMissingBusinessException: Raised if the predefined azure container doesn't exist.
    """
    logging.info("Searching for Default '%s' Container.", constants.DEFAULT_BLOB_CONTAINER)

    container_list = [container.name for container in utils.blob_service_client().list_containers()]
    if not constants.DEFAULT_BLOB_CONTAINER in container_list:
        raise FolderMissingBusinessException(f"Container '{constants.DEFAULT_BLOB_CONTAINER}' does not exist.")

    logging.info("Found '%s' Container, pulling blobs path now.", constants.DEFAULT_BLOB_CONTAINER)

    input_blobs_list = get_input_blobs_list()
    processed_blobs_list: list[InputBlob] = []

    for input_blob in input_blobs_list:
        try:
            logging.info("Starting analysis for '%s' ....", input_blob.inprogress_blob_path)
            processed_blob = analyze_blob(input_blob)
            processed_blobs_list.append(processed_blob)
            logging.info("Analysis completed successfully for '%s' ....", input_blob.inprogress_blob_path)
            input_blob = set_processing_status_and_move_completed_blobs(input_blob, False)

        except MissingConfigException:
            logging.exception(
                "A Missing Config error occurred while analyzing the document '%s'.",
                input_blob.inprogress_blob_path,
            )
            input_blob = set_processing_status_and_move_completed_blobs(input_blob, True)
            processed_blobs_list.append(input_blob)

        except CitadelIDPProcessingException:
            logging.exception(
                "A General Citadel IDP processing error occured while analyzing the document '%s'.",
                input_blob.inprogress_blob_path,
            )
            input_blob = set_processing_status_and_move_completed_blobs(input_blob, True)
            processed_blobs_list.append(input_blob)

        except Exception:
            logging.exception("An error occurred while analyzing the document '%s'.", input_blob.inprogress_blob_path)
            input_blob = set_processing_status_and_move_completed_blobs(input_blob, True)
            processed_blobs_list.append(input_blob)

    return processed_blobs_list


def get_input_blobs_list() -> list[InputBlob]:
    """
    Returns a list of input blobs from the provided folder.


    Returns:
        list[InputBlob]: The list of actionable input blobs.
    """
    input_blobs_list = []
    company_blobs_path_list = [
        path.name for path in utils.container_client().list_blobs(name_starts_with=constants.COMPANY_ROOT_FOLDER_PREFIX)
    ]

    if len(company_blobs_path_list) == 0:
        raise FolderMissingBusinessException(
            f"Folders with prefix '{constants.COMPANY_ROOT_FOLDER_PREFIX}' do not exist "
        )

    validation_successful_blobs_path_list = [
        item for item in company_blobs_path_list if constants.VALIDATION_SUCCESSFUL_SUBFOLDER in item
    ]

    if len(validation_successful_blobs_path_list) == 0:
        raise FolderMissingBusinessException(
            f"Either'{constants.VALIDATION_SUCCESSFUL_SUBFOLDER}' folders do not exist or '{constants.VALIDATION_SUCCESSFUL_SUBFOLDER}' folder is empty"
        )

    for validation_successful_blob_path in validation_successful_blobs_path_list:
        input_blobs_list.append(collect_input_blob(validation_successful_blob_path))

    logging.info("Total actionable blobs found is/are %s", len(input_blobs_list))
    return input_blobs_list


def collect_input_blob(validation_successful_blob_path: str) -> InputBlob:
    """
    Collects the sas_url of blob and converts that to `InputBlob` object.

    Args:
        blob_path (str): path of blob present in validation-successful folder.

    Returns:
        InputBlob: The collected input blob objet.
    """
    logging.info("Blob Path: %s", validation_successful_blob_path)
    blob_type, form_recognizer_model_id = utils.get_document_type_from_file_name(validation_successful_blob_path)
    input_blob = InputBlob(
        blob_type,
        form_recognizer_model_id,
        validation_successful_blob_path,
    )
    logging.info("blob type, rg_id: %s %s", input_blob.blob_type, input_blob.form_recognizer_model_id)
    # Adding Metadata
    input_blob.meta = utils.get_metadata("Validation", input_blob.validation_successful_blob_path)

    # Getting path to inprogress folder for this file path
    input_blob.inprogress_blob_path = input_blob.validation_successful_blob_path.replace(
        constants.VALIDATION_SUCCESSFUL_SUBFOLDER, constants.INPROGRESS_SUBFOLDER
    )

    # Moving blob from validation-successful to inprogress subfolder
    utils.move_blob(
        input_blob.validation_successful_blob_path,
        constants.VALIDATION_SUCCESSFUL_SUBFOLDER,
        constants.INPROGRESS_SUBFOLDER,
    )

    # Adding Metadata
    metadata = utils.get_metadata("Inprogress", input_blob.inprogress_blob_path)
    input_blob.meta = f"{input_blob.meta}\n{metadata}"

    # generating sas_url
    input_blob.inprogress_blob_url = utils.get_sas_url(input_blob.inprogress_blob_path)

    return input_blob


def set_processing_status_and_move_completed_blobs(input_blob: InputBlob, is_error: bool) -> InputBlob:
    """
    Sets the processing status and moves the completed blobs to appropriate subfolders.

    Args:
        input_blob (InputBlob): The input blob.
        is_error (bool): True if an error occurred during processing.

    Returns:
        InputBlob: The updated input blob.

    """
    if is_error:
        logging.info("Moving file '%s' to Failed folder.", input_blob.inprogress_blob_path)
        utils.move_blob(input_blob.inprogress_blob_path, constants.INPROGRESS_SUBFOLDER, constants.FAILED_SUBFOLDER)

        input_blob.failed_blob_path = input_blob.inprogress_blob_path.replace(
            constants.INPROGRESS_SUBFOLDER, constants.FAILED_SUBFOLDER
        )

        # Adding Metadata
        metadata = utils.get_metadata("Failed", input_blob.failed_blob_path)
        input_blob.meta = f"{input_blob.meta}\n{metadata}"

        input_blob.is_processed = True
        input_blob.is_successful = False
        input_blob.is_failed = True

    else:
        logging.info("Moving file '%s' to Successful folder.", input_blob.inprogress_blob_path)
        utils.move_blob(input_blob.inprogress_blob_path, constants.INPROGRESS_SUBFOLDER, constants.SUCCESSFUL_SUBFOLDER)

        input_blob.successful_blob_path = input_blob.inprogress_blob_path.replace(
            constants.INPROGRESS_SUBFOLDER, constants.SUCCESSFUL_SUBFOLDER
        )

        # Adding Metadata
        metadata = utils.get_metadata("Successful", input_blob.successful_blob_path)
        input_blob.meta = f"{input_blob.meta}\n{metadata}"

        input_blob.is_processed = True
        input_blob.is_successful = True
        input_blob.is_failed = False

    return input_blob
