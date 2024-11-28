import tarfile
from datetime import datetime, timedelta
from time import sleep

import os

from werkzeug.utils import secure_filename

from gevent.event import Event
from slivka_client import SlivkaClient

from config import SESSIONS_FOLDER, SLIVKA_URL, EXPIRATION_DAYS
from logger_config import setup_logging
from session_db import insert_metadata, update_status, update_slivka_id

custom_logger = setup_logging(name='submission')

class SubmissionHandler:
    """Handles FASTA file submissions and associated processing."""

    def __init__(self, session_id, form, service_type, config=None, tar_upload=False):
        """Initialize a SubmissionHandler instance.

        Args:
            session_id (str): Unique identifier for the submission session.
            form (FlaskForm): Form object containing the submission details.
            service_type (str): Type of service to use for processing.
            config (dict): Optional configuration dictionary.
            tar_upload (bool): Flag indicating if the upload is a tar file.
        """
        self.session_id = session_id
        self.form = form
        self.service_type = service_type
        self.config = config or {}
        self.tar_upload = tar_upload
        self.submission_time = datetime.now()
        self.session_directory = self.create_directory()
        self.submission_directory = self.create_submission_directory()
        self.filename = None
        self.file_path = None
        self.metadata_available = Event()  # Create an event to signal metadata availability

    def create_directory(self):
        """Create a directory for the submission session.

        Returns:
            str: The path to the created directory.
        """
        session_directory = os.path.join(SESSIONS_FOLDER, self.session_id)
        os.makedirs(session_directory, exist_ok=True)
        custom_logger.debug(f"Directory created for session {self.session_id}.")
        return session_directory
    
    def create_submission_directory(self):
        """Create a unique directory for each submission."""
        timestamp = self.submission_time.strftime('%Y%m%d%H%M%S')
        submission_directory = os.path.join(self.session_directory, f"{timestamp}")
        os.makedirs(submission_directory, exist_ok=True)
        custom_logger.debug(f"Directory created for submission {self.session_id}/{timestamp}.")
        return submission_directory
    
    def save_submission_data(self):
        """Save the uploaded data."""
        if self.tar_upload:
            self.file_path = os.path.join(self.submission_directory, 'submission.tar.gz')
            self.filename = 'submission.tar.gz'
            self.save_and_tar_files()
        else:
            self.save_sequence()

    def save_and_tar_files(self):
        """Save and tar the uploaded FASTA files."""
        with tarfile.open(self.file_path, "w:gz") as tar:
            for file in self.form.files.data:
                filename = secure_filename(file.filename)
                file_path = os.path.join(self.submission_directory, filename)
                file.save(file_path)
                tar.add(file_path, arcname=filename)
        custom_logger.info(f"Uploaded files saved and tarred for session {self.session_id}.")

    def save_sequence(self):
        """Save the uploaded FASTA file or the input sequence."""
        if self.form.fasta_file.data:
            self.filename = self.form.fasta_file.data.filename
            self.file_path = os.path.join(self.submission_directory, self.filename)
            self.form.fasta_file.data.save(self.file_path)
        else:
            self.filename = 'sequence.fasta'
            self.file_path = os.path.join(self.submission_directory, self.filename)
            with open(self.file_path, 'w') as f:
                f.write(self.form.sequence.data)
        custom_logger.info(f"FASTA data saved for session {self.session_id}.")

    def store_submission_metadata(self):
        """Insert metadata related to the submission into the database."""
        expiration_time = (self.submission_time + timedelta(days=EXPIRATION_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
        # TODO: output.fasta should be replaced with an actual output file name or some other meaningful result or ID
        insert_metadata(self.session_id, self.filename, 'output.fasta', self.submission_time.strftime('%Y-%m-%d %H:%M:%S'), 'uploaded', expiration_time)
        self.metadata_available.set()  # Signal that metadata is available
        custom_logger.info(f"Metadata inserted into database for session {self.session_id}.")

    def read_cached_submission(self):
        """Read the saved submission file.

        Returns:
            str or bytes: The content of the submission file.
        """
        if self.file_path.endswith(('.tar', '.tar.gz', '.tgz')):
            mode = 'rb'
        else:
            mode = 'r'
        
        with open(self.file_path, mode) as f:
            return f.read()

    def process_and_save_results(self, fasta_content):
        """Process the FASTA file content and save the results."""
        processor = SlivkaProcessor(SLIVKA_URL, service=self.service_type, session_id=self.session_id, filename=self.filename, config=self.config)
        output_file_path = os.path.join(self.submission_directory, 'output.fasta')
        success = processor.process_file(self.file_path, output_file_path, self.submission_directory)

    def update_db_status(self):
        """Update the processing status in the database."""
        update_status(self.session_id, self.filename, "processed")
        custom_logger.info(f"FASTA file processed and status updated for session {self.session_id}.")

    def handle_submission(self):
        """Handle the submission by orchestrating the various steps.

        Returns:
            dict: A dictionary containing the status, message, and other details of the submission.
        """
        result = {'status': 'failed', 'message': '', 'filename': None}

        try:
            self.save_submission_data()
            self.store_submission_metadata()
            fasta_content = self.read_cached_submission()
            self.process_and_save_results(fasta_content)
            self.update_db_status()
            result.update({
                'status': 'success',
                'message': 'File processed successfully.',
                'directory': self.session_directory,
                'filename': self.filename
            })
        except Exception as e:
            custom_logger.error(f"An error occurred while handling submission for session {self.session_id}: {str(e)}")
            result['status'] = 'failed'
            result['message'] = str(e)
        
        return result

    
class SlivkaProcessor:
    """Handles the processing of FASTA files using Slivka."""

    def __init__(self, slivka_url, service, session_id, filename, config=None):
        self.client = SlivkaClient(slivka_url)
        self.service = self.client[service]
        self.session_id = session_id
        self.filename = filename
        self.config = config or {}

    def process_file(self, input_file_path, output_file_path, submission_directory):
        """Process the given FASTA file using Slivka.

        Args:
            input_file_path (str): The path to the input FASTA file.
            output_file_path (str): The path where the output should be saved.

        Returns:
            bool: True if processing was successful, False otherwise.
        """
        try:
            # Open the FASTA file and set the media type
            with open(input_file_path, 'rb') as file_object:
                media_type = 'application/fasta'

                # Submit the job to Slivka 
                job = self.submit_job_to_slivka(file_object, media_type)

                # Wait for the job to complete
                self.wait_for_job_completion(job)

                # Download the job results
                self.download_job_results(job, submission_directory)

                # TODO: may not need this step if the output file is already saved
                # Copy Clustal Omega results (job.files[0].id) to the output file
                with open(os.path.join(submission_directory, job.files[0].id)) as result_file:
                    result = result_file.read()
                with open(output_file_path, 'w') as outfile:
                    outfile.write(result)

                return True
        except Exception as e:
            custom_logger.error(f"An error occurred while processing the FASTA file: {str(e)}")
            return False

    def submit_job_to_slivka(self, file_object, media_type):
        """Submit the given file to Slivka for processing.

        Args:
            file_object (file): The file object to submit.
            media_type (str): The media type of the file.

        Returns:
            SlivkaJob: The job object representing the submitted job.
        """
        data = self.config
        file_key = data.pop('file_key_override', 'input')

        # Create the 'files' dictionary with the correct format
        files = {
            file_key: (os.path.basename(file_object.name), file_object, media_type)
        }

        # Submit the job to Slivka
        job = self.service.submit_job(data=data, files=files)
        custom_logger.info(f"Job submitted: {job.id}")

        # Update the slivka_id in the database
        update_slivka_id(self.session_id, self.filename, job.id)

        return job
    
    def wait_for_job_completion(self, job):
        """Wait for the given job to complete.

        Args:
            job (SlivkaJob): The job object representing the submitted job.
        """
        # Wait for the job to complete
        while job.status not in ('COMPLETED', 'FAILED'):
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            custom_logger.info(f"Polling job status at {current_time}... (Status: {job.status})")
            sleep(3)  # Polling interval

        custom_logger.info(f"Completion Time: {job.completion_time}")

    def download_job_results(self, job, submission_directory):
        """Download the results of the given job to the specified directory.

        Args:
            job (SlivkaJob): The job object representing the completed job.
            submission_directory (str): The directory where the results should be saved.
        """
        # Download each file in the job results
        for file in job.files:
            # You can specify the local path where you want to save the file
            # TODO: Explore optimizing the local path
            local_path = os.path.join(*([submission_directory] + file.id.split('/')[1:]))  # remove slivka id prefix
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            file.dump(local_path)
            custom_logger.info(f"File {file.id} downloaded to {local_path}")