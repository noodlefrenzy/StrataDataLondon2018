## Create Custom VM
To use a custom VM image you first need to create a VM. To then create a VM image follow the steps in this link: https://docs.microsoft.com/en-us/azure/virtual-machines/linux/tutorial-custom-images

## Create a Service Principal and give it access to the resourge group where your VM image is
Then you will need to use a Service Principal instead of a Shared Key for authenticating against it otherwise you will get the following error:
AuthenticationErrorDetail:      The specified type of authentication SharedKey is not allowed when external resources of type Compute are linked.

To create a service principal do the following:
https://docs.microsoft.com/en-us/azure/azure-resource-manager/resource-group-create-service-principal-portal

The result will be something like the following:

SP name: your-sp
SP pw: yoursppassword
appID: your-application-id	App key: your-application-key	Directory (tentant) ID: yourtenantid

Give the Service Principal (app) access to your resource groups (containing files or vm images)

## Create a Batch service and run a sample tutorial
https://docs.microsoft.com/en-us/azure/batch/tutorial-parallel-python
then use *python_scoring_.py* scripts
## Container workloads in Azure Batch
https://docs.microsoft.com/en-us/azure/batch/batch-docker-container-workloads
