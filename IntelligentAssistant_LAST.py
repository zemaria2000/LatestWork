import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS
from settings import INFLUXDB, PREVIOUS_STEPS, INJECT_TIME_INTERVAL, VARIABLES, LIN_REG_VARS, EQUIPMENTS, MULTIPLIER
from keras.models import load_model
from datetime import timedelta
import numpy as np
import pandas as pd
import schedule
import os
from ClassAssistant import Email_Intelligent_Assistant
import joblib
import time
from datetime import datetime
import warnings
from influxdb_client.client.warnings import MissingPivotFunction
warnings.simplefilter("ignore", MissingPivotFunction)
import requests




# ------------------------------------------------------------------------------
# 1. SETTING SOME FIXED VARIABLES
data_bucket = INFLUXDB['Bucket']

# My email address and password (created by gmail) - see tutorial How to Send Emails Using Python - Plain Text, Adding Attachments, HTML Emails, and More
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')

# Variable to be used in the queries - I only want to make predictions when I know the last values are all in a row
time_range = int(INJECT_TIME_INTERVAL*PREVIOUS_STEPS + 3*INJECT_TIME_INTERVAL)
ad_time_range = int(2*INJECT_TIME_INTERVAL)

# Telegram Bot variables
API_Token = '6121421687:AAEZq-HQmCe9aW39dr_mHoK9e9csYMCgcF4'
GroupID = '-890547248' 


# -----------------------------------------------------------------------------
# 2. INSTANTIATING THE INFLUXDB CLIENT + THE EMAIL ASSISTANT TYPE OBJECT

# Instantiate the InfluxDB client
client = influxdb_client.InfluxDBClient(
    url = INFLUXDB['URL'],
    token = INFLUXDB['Token'],
    org = INFLUXDB['Org']
)
# Instantiate the write api client
write_api = client.write_api(write_options = SYNCHRONOUS)
# Instantiate the query api client
query_api = client.query_api()

# 3. STARTING OUR EMAIL ASSISTANT OBJECT
email_assistant = Email_Intelligent_Assistant(EMAIL_ADDRESS=EMAIL_ADDRESS, EMAIL_PASSWORD=EMAIL_PASSWORD, url = INFLUXDB['URL'], token = INFLUXDB['Token'], org = INFLUXDB['Org'], bucket = INFLUXDB['Bucket'])


# -----------------------------------------------------------------------------
# 2. MODEL LOADING FUNCTION

def model_loading():

    # Loading all the ML models
    # (don't know why, but the joblib.load only works for the Linear Regression models...)
    for var in VARIABLES:
        if var in LIN_REG_VARS:
            globals()[f'model_{var}'] = joblib.load(f'Models/{var}.h5')
        else:
            # globals()[f'model_{var}'] = joblib.load(f'Models/{var}.h5')
            globals()[f'model_{var}'] = load_model(f'Models/{var}.h5')

        # Loading the model history
        globals()[f'{var}_history'] = np.load(f'Models/{var}.npy',allow_pickle='TRUE').item()
        # loading the scalers with joblib works just fine...
        globals()[f'scaler_{var}'] = joblib.load(f'Scalers/{var}.scale')

    print('Models successfully loaded!! \n\n')
    
    # Loading the thresholds as well - they might differ after the new models have been created
    global thresholds
    thresholds = dict()
    # Getting all the values of the RMSEs
    for var in VARIABLES:
        thresholds[var] = globals()[f'{var}_history']['val_root_mean_squared_error']*MULTIPLIER[var]
        # Load the newest thresholds onto the database
        msg = influxdb_client.Point(var) \
            .tag("DataType", "Thresholds") \
            .field("value", thresholds[var]) \
            .time(datetime.utcnow(), influxdb_client.WritePrecision.NS)
        write_api.write(bucket = data_bucket, org = INFLUXDB['Org'], record = msg)

    # Oredering them alphabetically
    thresholds = dict(sorted(thresholds.items()))

    return thresholds



# ------------------------------------------------------------------------------
# 4. TELEGRAM NOTIFICATION REGARDING ANOMALIES

def AnomaliesTelegram(var, norm_difference, threshold):

    # Editing the message to send
    if (norm_difference >= threshold) and (norm_difference < 5 * threshold):
        severity = 'light'
    elif (norm_difference >= 5 * threshold) and (norm_difference < 10 * threshold):
        severity = 'medium'
    elif (norm_difference >= 10 * threshold):
        severity = 'severe'      
    
    if severity != 'severe':
        msg = f"There has been a {severity} anomaly regarding variable {var}\n"
        msg += f"The error threshold of the anomaly is {round(threshold, 5)}, and the error between prediction and real value was {norm_difference}!\n"
    else:
        msg = "<b>SEVERE ANOMALY</b>\n"
        msg = f"There has been a {severity} anomaly regarding variable {var}\n"
        msg += f"The error threshold of the anomaly is {round(threshold, 5)}, and the error between prediction and real value was {norm_difference}!\n"
    
    # sending the notification
    try:
        URL = 'https://api.telegram.org/bot' + API_Token + '/sendMessage?chat_id=' + GroupID
        textdata = {"text": msg, 'parse_mode': 'HTML'}
        requests.request("POST", url = URL, params = textdata)
    except Exception as e:
        msg = str(e) + ": Exception occurred in SendMessageToTelegram"
        print(msg)    # Processing the info




# -----------------------------------------------------------------------------
# 5. DEFINING THE PREDICTIONS FUNCTION

def predictions():

    st = time.time()    

    for equip in EQUIPMENTS:
            
        # -----------------------------------------------------------------------------
        # Retrieving the necessary data to make a prediction (based on some of the settings)
        # influxDB documentation - https://docs.influxdata.com/influxdb/cloud/api-guide/client-libraries/python/
        # query to retrieve the data from the bucket relative to all the variables
        query = f'from(bucket:"{data_bucket}")\
            |> range(start: -{time_range}s)\
            |> sort(columns: ["_time"], desc: true)\
            |> limit(n: {PREVIOUS_STEPS})\
            |> filter(fn:(r) => r.DataType == "Real Data")\
            |> filter(fn:(r) => r.Equipment == "{equip}")'

        # Send the query defined above retrieving the needed data from the database
        result = query_api.query(org = INFLUXDB['Org'], query = query)


        for var in VARIABLES:

            # getting the scaler to normalize the results
            scaler = globals()[f'scaler_{var}']

            # getting the values
            vals = []
            for table in result:
                for record in table.records:
                    if var == record.get_measurement():
                        vals.append(record.get_value())

            # eliminating the latest value
            # vals.pop(-1)

            # If we have the correct amount of measurements to do a prediction
            if int(len(vals)) == PREVIOUS_STEPS:
                   
                # Normalizing the values
                vals = scaler.transform(np.array(vals).reshape(-1,1))
                
                # reverse the vector so that the last measurement is the last timestamp
                values = np.flip(vals)

                # Turning them into a numpy array, and reshaping so that it has the shape that we used to build the model
                array = np.array(values).reshape(1, PREVIOUS_STEPS)      

                # Making a prediction based on the values that were retrieved
                test_predict = globals()[f'model_{var}'].predict(array)

                # Retrieving the y prediction
                if var not in LIN_REG_VARS:
                    test_predict_y = test_predict[0][PREVIOUS_STEPS - 1]
                else:
                    test_predict_y = test_predict

                # Putting our value back on it's unnormalized form
                test_predict_y = globals()[f'scaler_{var}'].inverse_transform(np.array(test_predict_y, dtype = object).reshape(-1, 1))

                # getting the future timestamp
                actual_ts = table.records[0].get_time()
                global future_ts        # global so that I can use it in the assistant function easily
                future_ts = actual_ts + timedelta(seconds = INJECT_TIME_INTERVAL)

                # Sending the current prediction to a bucket 
                msg = influxdb_client.Point(var) \
                    .tag("DataType", "Prediction Data") \
                    .tag("Equipment", equip) \
                    .field("value", float(test_predict_y)) \
                    .time(future_ts, influxdb_client.WritePrecision.NS)
                write_api.write(bucket = data_bucket, org = INFLUXDB['Org'], record = msg)

                print(f'Predictions for {var} successfully sent to the database!')

            # In case we don't have the right amount of measurements
            elif int(len(vals)) < PREVIOUS_STEPS:
                print(f"Cannot do predictions for variable {var}, as there aren't enough consecutive measurements in the database")
                print(f"We need at least {PREVIOUS_STEPS} measurements, and we only have {int(len(vals))}")

        print('\n')

    et = time.time()

    elapsed_time = et - st

    print('---------------------------------------------------------------------')
    print('Execution time for the predictions:', elapsed_time, 'seconds')
    print('---------------------------------------------------------------------')




# -----------------------------------------------------------------------------
# 6. DEFINING THE ANOMALY DETECTION FUNCTION

def anomaly_detection():

    st = time.time() 

    for equip in EQUIPMENTS:
        
        # Generate an empty DataFrame to put the anomalies in

        anomaly_df = pd.DataFrame()

        anomalies = []

        # ------------------------------------------------------------------------------
        # RETRIEVING THE LAST 2 PREDICTED VALUES AND THE LAST REAL VALUE FOR EACH MEASUREMENT

        query = f'from(bucket:"{data_bucket}")\
            |> range(start: -{ad_time_range}s)\
            |> filter(fn:(r) => r.DataType == "Prediction Data" or r.DataType == "Real Data")\
            |> filter(fn:(r) => r.Equipment == "{equip}")\
            |> filter(fn:(r) => r._field == "value")\
            |> last()'
       
        # creating a dataframe with the data
        result_df = client.query_api().query_data_frame(org = INFLUXDB['Org'], query=query)

        if len(result_df) > 0:
            
            result_df = result_df[['_measurement', 'DataType', '_value', '_time']]
            ts = result_df.loc[0, '_time'].to_pydatetime()
            # filtering the dataframes - seperating them in two
            pred_df = result_df[result_df.loc[:, "DataType"] == "Prediction Data"]
            real_df = result_df[result_df.loc[:, "DataType"] == "Real Data"]

            aux_df = result_df[['DataType', '_time']]

        else:
            pred_df = pd.DataFrame()
            real_df = pd.DataFrame()
        
        # in case we have a measurement + a prediction made
        if (len(pred_df) > 0 and len(real_df) > 0) and (len(real_df) == len(pred_df)):
                        
            for var in VARIABLES:  
                
                times = result_df.loc[result_df['_measurement'] == var, '_time'].tolist()
                if abs(times[0] - times[1]) > timedelta(seconds = INJECT_TIME_INTERVAL/2):
                    print(f"Couldn't conduct the anomaly detection for variable {var}, as the timestamps for real and prediction values weren't corresponding")

                else:
                    # Normalizing the prediction and the real value
                    prediction = globals()[f'scaler_{var}'].transform(np.array([[pred_df.loc[pred_df['_measurement'] == var, '_value'].iloc[0]]]))
                    real = globals()[f'scaler_{var}'].transform(np.array([[real_df.loc[real_df['_measurement'] == var, '_value'].iloc[0]]]))
                    # getting the difference of the measurements to then use the rmse to determine what's an anomaly
                    norm_difference = round(np.abs(float(prediction) - float(real)), 5)
                    threshold = thresholds[var]

                    # Denormalizing the results
                    prediction = globals()[f'scaler_{var}'].inverse_transform(np.array(prediction))
                    real = globals()[f'scaler_{var}'].inverse_transform(np.array(real))

                    # Calculate the difference and send a notification if it exceeds the threshold
                    if norm_difference > threshold:
                        aux = {'Variable': var,
                            'Timestamp': ts.strftime("%H:%M:%S - %m/%d/%Y"),        
                            'Predicted Value': float(prediction),
                            'Real Value': float(real),
                            'Norm Difference': float(norm_difference),
                            'Thresholds': float(threshold)}
                        anomalies.append(aux)   

                        AnomaliesTelegram(var = var, norm_difference = norm_difference, threshold = threshold)

                    # Sending the Error values to the database
                    msg = influxdb_client.Point(var) \
                        .tag("DataType", "Difference") \
                        .tag("Equipment", equip) \
                        .field("value", norm_difference) \
                        .time(ts, influxdb_client.WritePrecision.NS)
                    write_api.write(bucket = data_bucket, org = INFLUXDB['Org'], record = msg)
                
                    print(f'Anomaly Detection successfully conducted for variable {var}')

            print('\nAnomaly detection finished. Waiting for the next batch of predictions\n')

        else:
            print(f"\nThere's no pair (measurement + prediction) in the last timestamp in order for us to detect anomalies \n")

        # Generating the anomalies DataFrame
        anomaly_df = pd.DataFrame(anomalies)

        # adding the anomalies to the report
        email_assistant.add_anomalies(anomaly_dataframe = anomaly_df)

    et = time.time()
    elapsed_time = et - st

    print('---------------------------------------------------------------------')
    print('Execution time for the anomaly detection operation:', elapsed_time, 'seconds')
    print('---------------------------------------------------------------------\n')



# -----------------------------------------------------------------------------
# 7. FUNCTION THAT PROCESSES DATA + SCHEDULLING IT

def data_processing():
    st = time.time() 
    # email_assistant.graph_plotting()
    email_assistant.send_email_notification()
    email_assistant.save_report()
    email_assistant.generate_blank_excel()

    et = time.time()
    elapsed_time = et - st

    print('---------------------------------------------------------------------')
    print('Execution time for the email sending operation:', elapsed_time, 'seconds')
    print('---------------------------------------------------------------------\n')

# Schedulling some functions
schedule.every(1).minute.do(data_processing)
schedule.every().hour.do(model_loading)


# -----------------------------------------------------------------------------
# 8. DEFINING THE FUNCTION THAT WILL RUN ALL

def main():

    latest_timestamp = None

    while True:  
        
        schedule.run_pending()

        query = f'from(bucket:"{data_bucket}")\
            |> range(start: -{time_range}s)\
            |> last()\
            |> filter(fn:(r) => r._measurement == "U_L1_N")\
            |> filter(fn:(r) => r.DataType == "Real Data")'
        
        result = query_api.query(org = INFLUXDB['Org'], query = query)

        for table in result:
            for record in table.records:
                new_latest_timestamp = record.get_time()
                # print(new_latest_timestamp)
                # print(latest_timestamp)
                # print('\n\n')

        if latest_timestamp is None or new_latest_timestamp > latest_timestamp:
            latest_timestamp = new_latest_timestamp
            
            # make the predictions only when new data has arrived
            predictions()
            # Then make the anomaly detection
            anomaly_detection()

        time.sleep(1/1000)


# Running the functions one first time
model_loading()
predictions()


# ---------------------------------------------------------------------------------
# INFINITE CYCLE

while True:

    # schedule.run_pending()

    main()
    # predictions()
    # time.sleep(INJECT_TIME_INTERVAL)
    # anomaly_detection()
