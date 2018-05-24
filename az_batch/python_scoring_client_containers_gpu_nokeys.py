# python_tutorial_client.py - Batch Python SDK tutorial sample
#
# Copyright (c) Microsoft Corporation
#
# All rights reserved.
#
# MIT License
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED *AS IS*, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from __future__ import print_function
import datetime
import os
import sys
import time
import string

try:
    input = raw_input
except NameError:
    pass

import azure.storage.blob as azureblob
import azure.batch.batch_service_client as batch
import azure.batch.batch_auth as batchauth
import azure.batch.models as batchmodels
from azure.batch import BatchServiceClient
from azure.common.credentials import ServicePrincipalCredentials

sys.path.append('.')
sys.path.append('..')
import common_helpers  # noqa

# Update the Batch and Storage account credential strings below with the values
# unique to your accounts. These are used when constructing connection strings
# for the Batch and Storage client objects.
_BATCH_ACCOUNT_NAME = 'yourbatchaccount'
_BATCH_ACCOUNT_KEY = 'yourbatchkey=='
_BATCH_ACCOUNT_URL = 'https://yourbatchaccount.yourregion.batch.azure.com'

_ACR_USER_NAME = 'yourACRname'
_ACR_PASSW = 'yourACRpassw'
_ACR_URL = 'yourACRname.azurecr.io'
_ACR_IMG_NAME = _ACR_URL+'/ghanaimg:azbatch-gpu' #url to your container image
_CUSTOM_VM_IMG_ID = '/subscriptions/yoursubscriptionid/resourceGroups/your-vmimg-rg/providers/Microsoft.Compute/images/yourdockergpuimg'

_STORAGE_ACCOUNT_NAME = 'yourstorageaccount'
_STORAGE_ACCOUNT_KEY = 'yourstorageaccountkey=='
_STORAGE_INPUT_CONTAINER = 'tiles-toscore'
_STORAGE_OUTPUT_CONTAINER = 'tile-scores'

_POOL_ID = 'TileScorePool'
_POOL_NODE_COUNT = 3
_POOL_VM_SIZE = 'Standard_NC6' #'Standard_NC6' # if image is with GPU 133 h (8 mins per task)
_NODE_OS_PUBLISHER = 'Canonical'
_NODE_OS_OFFER = 'UbuntuServer'
_NODE_OS_SKU = '16'

_JOB_ID = _POOL_ID + 'Job'
startqkey='0333313'
tiles_per_job = 4*4096 #65536
tasks_per_job = 4


_TUTORIAL_TASK_FILE = 'python_scoring_task.py'
_ENV_YML_FILE = 'conda_dependencies_score.yml'

CLIENT_ID='yourServicePrincipalID'
SECRET='yourSPsecret'
TENANT_ID='yourtenantID'

_HR_TIMEOUT=24


def query_yes_no(question, default="no"):
    """
    Prompts the user for yes/no input, displaying the specified question text.

    :param str question: The text of the prompt for input.
    :param str default: The default if the user hits <ENTER>. Acceptable values
    are 'yes', 'no', and None.
    :rtype: str
    :return: 'yes' or 'no'
    """
    valid = {'y': 'yes', 'n': 'no'}
    if default is None:
        prompt = ' [y/n] '
    elif default == 'yes':
        prompt = ' [Y/n] '
    elif default == 'no':
        prompt = ' [y/N] '
    else:
        raise ValueError("Invalid default answer: '{}'".format(default))

    while 1:
        choice = input(question + prompt).lower()
        if default and not choice:
            return default
        try:
            return valid[choice[0]]
        except (KeyError, IndexError):
            print("Please respond with 'yes' or 'no' (or 'y' or 'n').\n")


def print_batch_exception(batch_exception):
    """
    Prints the contents of the specified Batch exception.

    :param batch_exception:
    """
    print('-------------------------------------------')
    print('Exception encountered:')
    if batch_exception.error and \
            batch_exception.error.message and \
            batch_exception.error.message.value:
        print(batch_exception.error.message.value)
        if batch_exception.error.values:
            print()
            for mesg in batch_exception.error.values:
                print('{}:\t{}'.format(mesg.key, mesg.value))
    print('-------------------------------------------')


def upload_file_to_container(block_blob_client, container_name, file_path):
    """
    Uploads a local file to an Azure Blob storage container.
    
    :param block_blob_client: A blob service client.
    :type block_blob_client: `azure.storage.blob.BlockBlobService`
    :param str container_name: The name of the Azure Blob storage container.
    :param str file_path: The local path to the file.
    :rtype: `azure.batch.models.ResourceFile`
    :return: A ResourceFile initialized with a SAS URL appropriate for Batch
    tasks.
    """
    blob_name = os.path.basename(file_path)
    print('Uploading file {} to container [{}]...'.format(file_path,
                                                          container_name))   
    block_blob_client.create_blob_from_path(container_name,
                                            blob_name,
                                            file_path)  
    sas_token = block_blob_client.generate_blob_shared_access_signature(
        container_name,
        blob_name,
        permission=azureblob.BlobPermissions.READ,
        expiry=datetime.datetime.utcnow() + datetime.timedelta(hours=2))
    sas_url = block_blob_client.make_blob_url(container_name,
                                              blob_name,
                                              sas_token=sas_token)
    return batchmodels.ResourceFile(file_path=blob_name,
                                    blob_source=sas_url)


def get_container_sas_token(block_blob_client,
                            container_name, blob_permissions, hours_timeout):
    """
    Obtains a shared access signature granting the specified permissions to the
    container.

    :param block_blob_client: A blob service client.
    :type block_blob_client: `azure.storage.blob.BlockBlobService`
    :param str container_name: The name of the Azure Blob storage container.
    :param BlobPermissions blob_permissions:
    :rtype: str
    :return: A SAS token granting the specified permissions to the container.
    """
    # Obtain the SAS token for the container, setting the expiry time and
    # permissions. In this case, no start time is specified, so the shared
    # access signature becomes valid immediately.
    container_sas_token = \
        block_blob_client.generate_container_shared_access_signature(
            container_name,
            permission=blob_permissions,
            expiry=datetime.datetime.utcnow() + datetime.timedelta(hours=hours_timeout))
    return container_sas_token


def create_pool(batch_service_client, pool_id,
                resource_files, publisher, offer, sku):
    """
    Creates a pool of compute nodes with the specified OS settings.

    :param batch_service_client: A Batch service client.
    :type batch_service_client: `azure.batch.BatchServiceClient`
    :param str pool_id: An ID for the new pool.
    :param list resource_files: A collection of resource files for the pool's
    start task.
    :param str publisher: Marketplace image publisher
    :param str offer: Marketplace image offer
    :param str sku: Marketplace image sku
    """
    print('Creating pool [{}]...'.format(pool_id))

    # Create a new pool of Linux compute nodes using an Azure Virtual Machines
    # Marketplace image. For more information about creating pools of Linux
    # nodes, see:
    # https://azure.microsoft.com/documentation/articles/batch-linux-nodes/

    # Specify the commands for the pool's start task. The start task is run
    # on each node as it joins the pool, and when it's rebooted or re-imaged.
    # We use the start task to prep the node for running our task script.
    task_commands = [
        # Copy the python_tutorial_task.py script to the "shared" directory
        # that all tasks that run on the node have access to. Note that
        # we are using the -p flag with cp to preserve the file uid/gid,
        # otherwise since this start task is run as an admin, it would not
        # be accessible by tasks run as a non-admin user.
        #'wget https://packages.microsoft.com/config/ubuntu/16.04/packages-microsoft-prod.deb',
        #'sudo dpkg -i packages-microsoft-prod.deb',
        'wget -O azcopy.tar.gz https://aka.ms/downloadazcopylinux64',
        'tar -xf azcopy.tar.gz',
        'sudo ./install.sh',
        'wget https://repo.anaconda.com/archive/Anaconda3-5.1.0-Linux-x86_64.sh -O ~/conda.sh',
        'bash ~/conda.sh -b -p $AZ_BATCH_NODE_SHARED_DIR/conda',
        'export PATH="$AZ_BATCH_NODE_SHARED_DIR/conda/bin:$PATH"',
        'sudo apt-get -y update',
        #'sudo apt-get -y install azcopy',
        'cp -p {} $AZ_BATCH_NODE_SHARED_DIR'.format(_TUTORIAL_TASK_FILE),
        'cp -p {} $AZ_BATCH_NODE_SHARED_DIR'.format(_ENV_YML_FILE),
        'azcopy --source https://{0}.blob.core.windows.net/model/ghanamines.h5 --destination $AZ_BATCH_NODE_SHARED_DIR/ghanamines.h5 --source-key {1}'.format(_STORAGE_ACCOUNT_NAME, _STORAGE_ACCOUNT_KEY),
        'sudo $AZ_BATCH_NODE_SHARED_DIR/conda/bin/conda env create -f {}'.format(_ENV_YML_FILE)
        ] 
        


    # Get the node agent SKU and image reference for the virtual machine
    # configuration.
    # For more information about the virtual machine configuration, see:
    # https://azure.microsoft.com/documentation/articles/batch-linux-nodes/
    sku_to_use, image_ref_to_use = \
        common_helpers.select_latest_verified_vm_image_with_node_agent_sku(
            batch_service_client, publisher, offer, sku)
    user = batchmodels.AutoUserSpecification(
        scope=batchmodels.AutoUserScope.pool,
        elevation_level=batchmodels.ElevationLevel.admin)
    new_pool = batch.models.PoolAddParameter(
        id=pool_id,
        virtual_machine_configuration=batchmodels.VirtualMachineConfiguration(
            image_reference=image_ref_to_use,
            node_agent_sku_id=sku_to_use),
        vm_size=_POOL_VM_SIZE,
        target_dedicated_nodes=_POOL_NODE_COUNT,
        start_task=batch.models.StartTask(
            command_line=common_helpers.wrap_commands_in_shell('linux',
                                                               task_commands),
            user_identity=batchmodels.UserIdentity(auto_user=user),
            wait_for_success=True,
            resource_files=resource_files),
    )

    try:
        batch_service_client.pool.add(new_pool)
    except batchmodels.batch_error.BatchErrorException as err:
        print_batch_exception(err)
        raise


def create_pool_with_containers(batch_service_client, pool_id,
                resource_files, publisher, offer, sku):
    """
    Creates a pool of compute nodes with the specified OS settings.

    :param batch_service_client: A Batch service client.
    :type batch_service_client: `azure.batch.BatchServiceClient`
    :param str pool_id: An ID for the new pool.
    :param list resource_files: A collection of resource files for the pool's
    start task.
    :param str publisher: Marketplace image publisher
    :param str offer: Marketplace image offer
    :param str sku: Marketplace image sku
    """
    print('Creating pool [{}]...'.format(pool_id))

    # Create a new pool of Linux compute nodes using an Azure Virtual Machines
    # Marketplace image. For more information about creating pools of Linux
    # nodes, see:
    # https://azure.microsoft.com/documentation/articles/batch-linux-nodes/

    # Specify the commands for the pool's start task. The start task is run
    # on each node as it joins the pool, and when it's rebooted or re-imaged.
    # We use the start task to prep the node for running our task script.
    task_commands = [
        # Copy the python_tutorial_task.py script to the "shared" directory
        # that all tasks that run on the node have access to. Note that
        # we are using the -p flag with cp to preserve the file uid/gid,
        # otherwise since this start task is run as an admin, it would not
        # be accessible by tasks run as a non-admin user.
        #'wget https://packages.microsoft.com/config/ubuntu/16.04/packages-microsoft-prod.deb',
        #'sudo dpkg -i packages-microsoft-prod.deb',
        #'wget -O azcopy.tar.gz https://aka.ms/downloadazcopylinux64',
        #'tar -xf azcopy.tar.gz',
        #'sudo ./install.sh',
        #'wget https://repo.anaconda.com/archive/Anaconda3-5.1.0-Linux-x86_64.sh -O ~/conda.sh',
        #'bash ~/conda.sh -b -p $AZ_BATCH_NODE_SHARED_DIR/conda',
        #'export PATH="$AZ_BATCH_NODE_SHARED_DIR/conda/bin:$PATH"',
        #'sudo apt-get -y update',
        #'sudo apt-get -y install azcopy',
        'cp -p {} $AZ_BATCH_NODE_SHARED_DIR'.format(_TUTORIAL_TASK_FILE),
        #'cp -p {} $AZ_BATCH_NODE_SHARED_DIR'.format(_ENV_YML_FILE),
        'azcopy --source https://{0}.blob.core.windows.net/model/ghanamines.h5 --destination $AZ_BATCH_NODE_SHARED_DIR/ghanamines.h5 --source-key {1}'.format(_STORAGE_ACCOUNT_NAME, _STORAGE_ACCOUNT_KEY),
        #'sudo $AZ_BATCH_NODE_SHARED_DIR/conda/bin/conda env create -f {}'.format(_ENV_YML_FILE)
        ] 

    # Get the node agent SKU and image reference for the virtual machine
    # configuration.
    # For more information about the virtual machine configuration, see:
    # https://azure.microsoft.com/documentation/articles/batch-linux-nodes/
    sku_to_use, image_ref_to_use = \
        common_helpers.select_latest_verified_vm_image_with_node_agent_sku(
            batch_service_client, publisher, offer, sku)

    user = batchmodels.AutoUserSpecification(
        scope=batchmodels.AutoUserScope.pool,
        elevation_level=batchmodels.ElevationLevel.admin)

    container_reg = batchmodels.ContainerRegistry(user_name=CLIENT_ID, password=SECRET, registry_server=_ACR_URL)
    container_cfg = batchmodels.ContainerConfiguration(container_image_names=[_ACR_IMG_NAME], container_registries=[container_reg])
    my_img_ref= batchmodels.ImageReference(virtual_machine_image_id = _CUSTOM_VM_IMG_ID)
    
    vm_cfg = batchmodels.VirtualMachineConfiguration(
            image_reference=my_img_ref,
            node_agent_sku_id=sku_to_use,#'batch.node.ubuntu 16.04', ##verificare che l'immagine ghanaimg abbia gpu
            container_configuration=container_cfg)
    task_containersettings = batchmodels.TaskContainerSettings(image_name=_ACR_IMG_NAME)

    new_pool= batchmodels.PoolAddParameter(
        id=pool_id, 
        virtual_machine_configuration=vm_cfg,
        vm_size=_POOL_VM_SIZE,
        target_dedicated_nodes=_POOL_NODE_COUNT,
        target_low_priority_nodes=1,
        start_task=batch.models.StartTask(
            command_line=common_helpers.wrap_commands_in_shell('linux',
                                                               task_commands),
            user_identity=batchmodels.UserIdentity(auto_user=user),
            wait_for_success=True
            ,resource_files=resource_files
            , container_settings = task_containersettings
            )
        )


    try:
        batch_service_client.pool.add(new_pool)
    except batchmodels.batch_error.BatchErrorException as err:
        print_batch_exception(err)
        raise


def create_job(batch_service_client, job_id, pool_id, pattern):
    """
    Creates a job with the specified ID, associated with the specified pool.

    :param batch_service_client: A Batch service client.
    :type batch_service_client: `azure.batch.BatchServiceClient`
    :param str job_id: The ID for the job.
    :param str pool_id: The ID for the pool.
    """
    print('Creating job [{}] for startqkey {}...'.format(job_id, pattern))
    
    prep_commands=[
        #'sudo docker run -it mlcrpacr31b520505a57.azurecr.io/ghanaimg:azbatch /bin/bash',
        'mkdir -p $AZ_BATCH_NODE_SHARED_DIR/tiles',
        'azcopy --source https://{0}.blob.core.windows.net/{1}/ ' \
        '--destination $AZ_BATCH_NODE_SHARED_DIR/tiles --source-key {2} ' \
        '--include "{3}" --recursive --exclude-older --exclude-newer --resume $AZ_BATCH_NODE_SHARED_DIR/journal'.format(
            _STORAGE_ACCOUNT_NAME,
            _STORAGE_INPUT_CONTAINER, 
            _STORAGE_ACCOUNT_KEY, 
            pattern)
        ] #modificare qui e fare il download delle immagini
    task_containersettings = batchmodels.TaskContainerSettings(image_name=_ACR_IMG_NAME)
    job_prep= batch.models.JobPreparationTask(
        command_line=common_helpers.wrap_commands_in_shell('linux', prep_commands),
        container_settings = task_containersettings) 
    job = batch.models.JobAddParameter(
        job_id,
        batch.models.PoolInformation(pool_id=pool_id),
        job_preparation_task = job_prep) 
    
    try:
        batch_service_client.job.add(job)
    except batchmodels.batch_error.BatchErrorException as err:
        print_batch_exception(err)
        raise


def add_tasks(batch_service_client, job_id, startqkey,
              output_container_name, output_container_sas_token):
    """
    Adds a task for each input file in the collection to the specified job.

    :param batch_service_client: A Batch service client.
    :type batch_service_client: `azure.batch.BatchServiceClient`
    :param str job_id: The ID of the job to which to add the tasks.
    :param list input_files: A collection of input files. One task will be
     created for each input file.
    :param output_container_name: The ID of an Azure Blob storage container to
    which the tasks will upload their results.
    :param output_container_sas_token: A SAS token granting write access to
    the specified Azure Blob storage container.

    container_settings
    TaskContainerSettings 
    The settings for the container under which the task runs. If the pool that 
    will run this task has containerConfiguration set, this must be set as well. 
    If the pool that will run this task doesn't have containerConfiguration set, 
    this must not be set. When this is specified, all directories recursively 
    below the AZ_BATCH_NODE_ROOT_DIR (the root of Azure Batch directories on the node) 
    are mapped into the container, all task environment variables are mapped 
    into the container, and the task command line is executed in the container.

    """

    print('Adding 1 tasks to job [{}]...'.format(job_id))

    task_containersettings = batchmodels.TaskContainerSettings(image_name=_ACR_IMG_NAME)

    tasks = list()

    for idx in range(tasks_per_job):
        taskqkey=startqkey + int2base(idx,4,1)

        command = [
                    'python $AZ_BATCH_NODE_SHARED_DIR/{} ' \
                    '--filedir $AZ_BATCH_NODE_SHARED_DIR/tiles ' \
                    '--model $AZ_BATCH_NODE_SHARED_DIR/ghanamines.h5 ' \
                    '--storageaccount {} ' \
                    '--storagecontainer {} --sastoken "{}" ' \
                    '--startqkey {}'.format(
                        _TUTORIAL_TASK_FILE,
                        _STORAGE_ACCOUNT_NAME,
                        output_container_name,
                        output_container_sas_token,
                        taskqkey)]

        print('adding task {}'.format(idx))

        tasks.append(batch.models.TaskAddParameter(
                'TileScoretask{:0>2}'.format(idx),
                common_helpers.wrap_commands_in_shell('linux', command),
                container_settings = task_containersettings,
                user_identity = batchmodels.UserIdentity(#user_name='root')
                    auto_user = batchmodels.AutoUserSpecification(
                        scope=batchmodels.AutoUserScope.task,
                        elevation_level=batchmodels.ElevationLevel.admin))
                )
        )

    batch_service_client.task.add_collection(job_id, tasks)


def wait_for_tasks_to_complete(batch_service_client, job_id, timeout):
    """
    Returns when all tasks in the specified job reach the Completed state.

    :param batch_service_client: A Batch service client.
    :type batch_service_client: `azure.batch.BatchServiceClient`
    :param str job_id: The id of the job whose tasks should be to monitored.
    :param timedelta timeout: The duration to wait for task completion. If all
    tasks in the specified job do not reach Completed state within this time
    period, an exception will be raised.
    """
    timeout_expiration = datetime.datetime.now() + timeout

    print("Monitoring all tasks for 'Completed' state for job {}, timeout in {}..."
          .format(job_id,timeout), end='')

    while datetime.datetime.now() < timeout_expiration:
        tasks = batch_service_client.task.list(job_id)

        all_tasks = [t for t in tasks]

        incomplete_tasks = [task for task in all_tasks if
                            task.state != batchmodels.TaskState.completed]
        
        print('{0:.0%}..'.format(1-len(incomplete_tasks)/len(all_tasks)), end='')
        sys.stdout.flush()
        if not incomplete_tasks:
            print()
            return True
        else:
            time.sleep(15)

    print()
    raise RuntimeError("ERROR: Tasks did not reach 'Completed' state within "
                       "timeout period of " + str(timeout))
def check_for_tasks_to_complete(batch_service_client, job_id):
    """
    Returns when all tasks in the specified job reach the Completed state.

    :param batch_service_client: A Batch service client.
    :type batch_service_client: `azure.batch.BatchServiceClient`
    :param str job_id: The id of the job whose tasks should be to monitored.
    :param timedelta timeout: The duration to wait for task completion. If all
    tasks in the specified job do not reach Completed state within this time
    period, an exception will be raised.
    """
    tasks = batch_service_client.task.list(job_id)

    all_tasks = [t for t in tasks]

    incomplete_tasks = [task for task in all_tasks if
                        task.state != batchmodels.TaskState.completed]
    
    if not incomplete_tasks:
        return True
    else:
        return False


def wait_for_jobs_to_complete(batch_service_client, job_ids, timeout):
    """
    Returns when all tasks in the specified job reach the Completed state.

    :param batch_service_client: A Batch service client.
    :type batch_service_client: `azure.batch.BatchServiceClient`
    :param str job_id: The id of the job whose tasks should be to monitored.
    :param timedelta timeout: The duration to wait for task completion. If all
    tasks in the specified job do not reach Completed state within this time
    period, an exception will be raised.
    """
    timeout_expiration = datetime.datetime.now() + timeout

    print("Monitoring all jobs for 'Completed' state, timeout in {}..."
          .format(timeout), end='')

    while datetime.datetime.now() < timeout_expiration:
        for job_id in job_ids:
            print("checking job_id {}...".format(job_id))
            if check_for_tasks_to_complete(batch_service_client,job_id):
                batch_client.job.delete(jobid)
                return True
        time.sleep(15)
    return False



def download_blobs_from_container(block_blob_client,
                                  container_name, directory_path):
    """
    Downloads all blobs from the specified Azure Blob storage container.

    :param block_blob_client: A blob service client.
    :type block_blob_client: `azure.storage.blob.BlockBlobService`
    :param container_name: The Azure Blob storage container from which to
     download files.
    :param directory_path: The local directory to which to download the files.
    """
    print('Downloading all files from container [{}]...'.format(
        container_name))

    container_blobs = block_blob_client.list_blobs(container_name)

    for blob in container_blobs.items:
        destination_file_path = os.path.join(directory_path, blob.name)

        block_blob_client.get_blob_to_path(container_name,
                                           blob.name,
                                           destination_file_path)

        print('  Downloaded blob [{}] from container [{}] to {}'.format(
            blob.name,
            container_name,
            destination_file_path))

    print('  Download complete!')

def int2base(x, base,strlen, digs=string.digits + string.ascii_letters):
    if x < 0:
        sign = -1
    elif x == 0:
        return digs[0]*strlen
    else:
        sign = 1
    x *= sign
    digits = []
    while x:
        digits.append(digs[int(x % base)])
        x //= base
    if strlen>len(digits):
        digits += '0'*(strlen - len(digits))
    if sign < 0:
        digits.append('-')
    digits.reverse()
    return ''.join(digits)


if __name__ == '__main__':

    start_time = datetime.datetime.now().replace(microsecond=0)
    print('Sample start: {}'.format(start_time))
    print()

    # Create the blob client, for use in obtaining references to
    # blob storage containers and uploading files to containers.
    blob_client = azureblob.BlockBlobService(
        account_name=_STORAGE_ACCOUNT_NAME,
        account_key=_STORAGE_ACCOUNT_KEY)
    

    
    # Use the blob client to create the containers in Azure Storage if they
    # don't yet exist.
    app_container_name = 'batchjobfiles'
    #input_container_name = 'input'
    #output_container_name = 'output'
    blob_client.create_container(app_container_name, fail_on_exist=False)
    #blob_client.create_container(input_container_name, fail_on_exist=False)
    #blob_client.create_container(output_container_name, fail_on_exist=False)

    # Paths to the task script. This script will be executed by the tasks that
    # run on the compute nodes.
    application_file_paths = [os.path.realpath(_TUTORIAL_TASK_FILE)]
    application_file_paths.append(os.path.realpath(_ENV_YML_FILE))

    # The collection of data files that are to be processed by the tasks.
    #input_file_paths = [os.path.realpath('./data/taskdata1.txt'),
    #                    os.path.realpath('./data/taskdata2.txt'),
    #                    os.path.realpath('./data/taskdata3.txt')]

    # Upload the application script to Azure Storage. This is the script that
    # will process the data files, and is executed by each of the tasks on the
    # compute nodes.
    application_files = [
        upload_file_to_container(blob_client, app_container_name, file_path)
        for file_path in application_file_paths]

    # Upload the data files. This is the data that will be processed by each of
    # the tasks executed on the compute nodes in the pool.
    #input_files = [
    #    upload_file_to_container(blob_client, input_container_name, file_path)
    #    for file_path in input_file_paths]
    

    # Obtain a shared access signature that provides write access to the output
    # container to which the tasks will upload their output.
    output_container_sas_token = get_container_sas_token(
        blob_client,
        _STORAGE_OUTPUT_CONTAINER,
        azureblob.BlobPermissions.WRITE,
        _HR_TIMEOUT)
    
    input_container_sas_token = get_container_sas_token(
        blob_client,
        _STORAGE_INPUT_CONTAINER,
        azureblob.BlobPermissions.WRITE+azureblob.BlobPermissions.READ, _HR_TIMEOUT)

    '''
    # Create a Batch service client. We'll now be interacting with the Batch
    # service in addition to Storage
    credentials = batchauth.SharedKeyCredentials(_BATCH_ACCOUNT_NAME,
                                                 _BATCH_ACCOUNT_KEY)

    batch_client = batch.BatchServiceClient(
        credentials,
        base_url=_BATCH_ACCOUNT_URL)
    '''
    credentials = ServicePrincipalCredentials(
        client_id=CLIENT_ID,
        secret=SECRET,
        tenant=TENANT_ID,
        resource="https://batch.core.windows.net/"
    )
    batch_client = BatchServiceClient(
        credentials,
        base_url=_BATCH_ACCOUNT_URL
    )

    # filedirs=range(0,10000)
    # blobnames_list= ['gist_out_{:0>4}.json'.format(f) for f in filedirs]
    # blobsdone = []
    # for i in range(10):
    #     # list_blobs returns only max 5000 blobs
    #     blobsdone = blobsdone + [blob.name for blob in blob_client.list_blobs(container_name=_STORAGE_OUTPUT_CONTAINER, prefix='gist_out_{}'.format(i))]
    
    # blobstodo= [b for b in blobnames_list if b not in blobsdone]
    # blobdirs=[c.split("_")[2].split(".")[0] for c in blobstodo]
    # blobstodo = [b.name for b in blob_client.list_blobs(container_name=_STORAGE_INPUT_CONTAINER)]


    # Create the pool that will contain the compute nodes that will execute the
    # tasks. The resource files we pass in are used for configuring the pool's
    # start task, which is executed each time a node first joins the pool (or
    # is rebooted or re-imaged).
    if query_yes_no('Create new pool?') == 'yes':
        create_pool_with_containers(batch_client,
                    _POOL_ID,
                    application_files,
                    _NODE_OS_PUBLISHER,
                    _NODE_OS_OFFER,
                    _NODE_OS_SKU)
    
    ntilesbase4='3'*(18-len(startqkey))
    ntiles = int(ntilesbase4,4)+1

    jobids=[ _JOB_ID+'_'+'{:0>4}'.format(str(i)) for i in range(int(ntiles/tiles_per_job))]

    wait_completion = False
    if query_yes_no('wait for jobs to complete')=='yes':
        wait_completion = True
    
  
    
    for idx,jobid in enumerate(jobids):
        if wait_completion:
            wait_for_jobs_to_complete(batch_client,
                                    jobids,
                                    datetime.timedelta(hours=_HR_TIMEOUT))

        # Create the job that will run the tasks.
        stqkey=startqkey+int2base(idx,4,len(int2base(int(ntiles/tiles_per_job)-1,4,1)))
        create_job(batch_client, jobid, _POOL_ID, stqkey)

        # Add the tasks to the job. We need to supply a container shared access
        # signature (SAS) token for the tasks so that they can upload their output
        # to Azure Storage.
        add_tasks(batch_client,
                jobid,
                stqkey,
                _STORAGE_OUTPUT_CONTAINER,
                output_container_sas_token)
        
        # Pause execution until tasks reach Completed state.
        wait_for_tasks_to_complete(batch_client,
                            jobid,
                            datetime.timedelta(hours=_HR_TIMEOUT))
        batch_client.job.delete(jobid)

    print("  Success! All tasks reached the 'Completed' state within the "
        "specified timeout period.")

    # # Download the task output files from the output Storage container to a
    # # local directory. Note that we could have also downloaded the output
    # # files directly from the compute nodes themselves.
    # download_blobs_from_container(blob_client,
    #                               _STORAGE_OUTPUT_CONTAINER,
    #                               os.path.expanduser('~'))

    # Print out some timing info
    end_time = datetime.datetime.now().replace(microsecond=0)
    print()
    print('Sample end: {}'.format(end_time))
    print('Elapsed time: {}'.format(end_time - start_time))
    print()

    # Clean up Batch resources (if the user so chooses).
    # if query_yes_no('Delete job(s)?') == 'yes':
    #     batch_client.job.delete(_JOB_ID)

    if query_yes_no('Delete pool?') == 'yes':
        batch_client.pool.delete(_POOL_ID)

    print()
    input('Press ENTER to exit...')