# This script generates the scoring and schema files
# necessary to operationalize your model
from azureml.api.schema.dataTypes import DataTypes
from azureml.api.schema.sampleDefinition import SampleDefinition
from azureml.api.realtime.services import generate_schema
import json
import numpy as np
import os
import base64, io
from PIL import Image
from azure.storage.blob import BlockBlobService

# Prepare the web service definition by authoring
# init() and run() functions. Test the functions
# before deploying the web service.

model = None

def init():
    # Get the path to the model asset
    # local_path = get_local_path('mymodel.model.link')    
    # Load model using appropriate library and function
    global model
    global labels
    # model = model_load_function(local_path)
    model_name = 'yourmodel.h5'
    from keras.models import load_model 
    model = load_model(model_name)
    labels = {0: 'iscloud', 1: 'ismine', 2: 'isnone'}

def run(input_array):
    base64ImgString = input_array[0]
    pil_img = base64ToPilImg(base64ImgString)
    image_np = load_image_into_numpy_array(pil_img)
    image_np_expanded = np.expand_dims(image_np, axis=0)
    x = image_np
    x = np.expand_dims(x, axis=0)
    y = model.predict(x)
    result = '{"class": ' + json.dumps(labels[np.argmax(y[0])]) + ' , "score": ' + json.dumps(float(np.max(y[0]))) + '}' #
    resultString = '{"output":' + result + '}'
    return resultString

def generate_api_schema():
    import os
    print("create schema")
    sample_input = "sample data text"
    inputs = {"input_df": SampleDefinition(DataTypes.STANDARD, sample_input)}
    os.makedirs('outputs', exist_ok=True)
    print(generate_schema(inputs=inputs, filepath="outputs/schema.json", run_func=run))

def base64ToPilImg(base64ImgString):
    if base64ImgString.startswith('b\''):
        base64ImgString = base64ImgString[2:-1]
    base64Img   =  base64ImgString.encode('utf-8')
    decoded_img = base64.b64decode(base64Img)
    img_buffer  = io.BytesIO(decoded_img)
    pil_img = Image.open(img_buffer).convert('RGB')
    return pil_img

def pilImgToBase64(pilImg):
    pilImg = pilImg.convert('RGB') #not sure this is necessary
    imgio = io.BytesIO()
    pilImg.save(imgio, 'PNG')
    imgio.seek(0)
    dataimg = base64.b64encode(imgio.read())
    return dataimg.decode('utf-8')

def load_image_into_numpy_array(image):
  (im_width, im_height) = image.size
  return np.array(image.getdata()).reshape(
      (im_height, im_width, 3)).astype(np.uint8)

# Implement test code to run in IDE or Azure ML Workbench
if __name__ == '__main__':
    from azureml.api.schema.dataTypes import DataTypes
    from azureml.api.schema.sampleDefinition import SampleDefinition
    from azureml.api.realtime.services import generate_schema

    # Import the logger only for Workbench runs
    #from azureml.logging import get_azureml_logger
    #logger = get_azureml_logger()

    init()

    pilImg = Image.open("yourimage.jpg")
    base64ImgString = pilImgToBase64(pilImg)
    np_imgstring = np.array([base64ImgString], dtype=np.unicode)
    inputs = {"input_array": SampleDefinition(DataTypes.NUMPY, np_imgstring)}
    resultString = run(np_imgstring)
    print("resultString = " + str(resultString))

    # Genereate the schema
    generate_schema(run_func=run, inputs=inputs, filepath='service_schema.json')
    print("Schema generated.")
