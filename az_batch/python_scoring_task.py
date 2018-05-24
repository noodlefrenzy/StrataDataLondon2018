
from __future__ import print_function
import argparse
import os, base64, io, string
import azure.storage.blob as azureblob
import numpy as np
from PIL import Image
import json
from keras.models import load_model
from azure.storage.blob import BlockBlobService


def load_image_into_numpy_array(image):
  (im_width, im_height) = image.size
  return np.array(image.getdata()).reshape(
      (im_height, im_width, 3)).astype(np.uint8)

def int2base(x, base,maxlen=11, digs=string.digits + string.ascii_letters):
    if x < 0:
        sign = -1
    elif x == 0:
        return digs[0]*maxlen
    else:
        sign = 1
    x *= sign
    digits = []
    while x:
        digits.append(digs[int(x % base)])
        x //= base
    if maxlen>len(digits):
        digits += '0'*(maxlen - len(digits))
    if sign < 0:
        digits.append('-')
    digits.reverse()
    return ''.join(digits)

if __name__ == '__main__':
   
    parser = argparse.ArgumentParser()
    parser.add_argument('--filedir', required=True,
                        help='The dir name of images to process. The path'
                             'may include a compute node\'s environment'
                             'variables, such as'
                             '$AZ_BATCH_NODE_SHARED_DIR/filename.txt')
    parser.add_argument('--model', required=True,
                        help='The full file path to the model. The path'
                             'may include a compute node\'s environment'
                             'variables, such as'
                             '$AZ_BATCH_NODE_SHARED_DIR/filename.txt')
    parser.add_argument('--storageaccount', required=True,
                        help='The name of the Azure Storage account that owns the'
                             'blob storage container to which to upload'
                             'results and from which to download images.')
    parser.add_argument('--storagecontainer', required=True,
                        help='The Azure Blob storage container to which to'
                             'upload results.')
    parser.add_argument('--sastoken', required=True,
                        help='The SAS token providing write access to the'
                             'Storage container.')
    parser.add_argument('--startqkey', required=False, default='0333313',
                        help='the range of images that this task has to process')

    args = parser.parse_args()

    filedir = args.filedir
    startqkey= args.startqkey
    
    model_name = args.model
    model = load_model(model_name)
    labels = {0: 'iscloud', 1: 'ismine', 2: 'isnone'}

    # Create the blob client using the input container's SAS token.
    # This allows us to create a client that provides read
    # access only to the container.
    #blob_client_out = azureblob.BlockBlobService(account_name=args.storageaccount,
    #                                         sas_token=args.sastoken)

    # blob_client = azureblob.BlockBlobService(
    #     account_name=args.storageaccount,
    #     account_key=args.accountkey)

    # blobs=blob_client.list_blobs(container_name=args.inputcontainer, prefix=filedir)    
    
    # blobs_to_process = [blob.name for blob in blobs if '.jpg' in blob.name ]

    # for blob in blobs_to_process:
    #     blob_client.get_blob_to_path(container_name=args.inputcontainer, blob_name= blob, file_path= blob.replace('/','_'))
    
    # local_file_names=[blob.replace('/','_') for blob in blobs_to_process]
    
    # imgdict={}
    # #imgdict['pippo']='pluto'
    # imgdict = create_color_gist(local_file_names)
    ntilesbase4='3'*(18-len(startqkey))
    ntiles = int(ntilesbase4,4)+1
    results = []
    for i in range(ntiles):
        ibase4=int2base(i,4, maxlen=18-len(startqkey))
        imgfile = os.path.join(filedir, startqkey+ ibase4 +".jpg")
        pilImg = Image.open(imgfile)
        x = load_image_into_numpy_array(pilImg)
        x = np.expand_dims(x, axis=0)
        y = model.predict(x)
        #result = 
        res = {"quadkey" : startqkey+ ibase4, "result": {"class": labels[np.argmax(y[0])] , "score": float(np.max(y[0])) }  } 
        results.append(res)        
        if i%100==0:
            print(i)
    # FINALLY
    output_file = 'score_out_'+startqkey+'.json'# needs to be the output dict, 
    # needs to have no headers to append to other results later
    # and the reference to the image something like 0000/fiename.jpg
    
    with open(output_file, 'w') as file:
       file.write(json.dumps(results))
    
    '''
    with open(output_file, "w") as text_file:
        print("------------------------------", file=text_file)
        print("Node: " + os.environ['AZ_BATCH_NODE_ID'], file=text_file)
        print("Task: " + os.environ['AZ_BATCH_TASK_ID'], file=text_file)
        print("Job:  " + os.environ['AZ_BATCH_JOB_ID'], file=text_file)
        print("Pool: " + os.environ['AZ_BATCH_POOL_ID'], file=text_file)
    '''

    # Create the blob client using the output container's SAS token.
    # This allows us to create a client that provides write
    # access only to the container.
    blob_client = azureblob.BlockBlobService(account_name=args.storageaccount,
                                             sas_token=args.sastoken)

    output_file_path = os.path.realpath(output_file)

    print('Uploading file {} to container [{}]...'.format(
        output_file_path,
        args.storagecontainer))

    blob_client.create_blob_from_path(args.storagecontainer,
                                      output_file,
                                      output_file_path)


    