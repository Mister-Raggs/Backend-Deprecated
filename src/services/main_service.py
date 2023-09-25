import logging

from common import config_reader
from common.custom_exceptions import CitadelIDPBackendException
from services import input_blob_handler


def start_flow():
    logging.info("Starting main app flow....")

    if config_reader.config_data.has_option("Main", "env"):
        env = config_reader.config_data.get("Main", "env")
    else:
        env = "local"

    logging.info("Environment is set as '%s'", env)
    processed_files_list = []

    if env.lower() == "local" or env.lower() == "prod":
        if config_reader.config_data.has_option("Main", "use-azure-blob-storage"):
            use_azure_blob_storage = config_reader.config_data.getboolean("Main", "use-azure-blob-storage")
        else:
            use_azure_blob_storage = True

        if use_azure_blob_storage:
            try:
                processed_files_list = input_blob_handler.handle_input_blob_process()
            except Exception as ex:
                raise CitadelIDPBackendException(ex) from ex
        else:
            logging.exception("If env is local or prod use-azure-blob-storage needs to be true")

    # Just logging the details here for now.
    logging.info("Final processing status dump....")
    for processed_file in processed_files_list:
        logging.info("Processed file info is: %s", processed_file)
