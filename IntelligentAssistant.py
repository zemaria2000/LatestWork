# This file tries to join the 'RealTimeAnomalyDetection.py' + 'RealTimePrediction.py' in one basically. The purpose is to be able to make a prediction almost as the same time as we recieve new data from the database
# However, this has some adaptations, because I'm only sending 4 vars in total from the ESPs. That's why I've put some for cycles in the mix and other things

# %%
import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS
from settings import INFLUXDB, PREVIOUS_STEPS, INJECT_TIME_INTERVAL, VARIABLES, AD_THRESHOLD, LIN_REG_VARS, EQUIPMENTS
from keras.models import load_model
from datetime import timedelta
import numpy as np
import pandas as pd
import schedule
import os
from ClassAssistant import Email_Intelligent_Assistant
import joblib



# ------------------------------------------------------------------------------
# 1. SETTING SOME FIXED VARIABLES
data_bucket = INFLUXDB['Bucket']

# My email address and password (created by gmail) - see tutorial How to Send Emails Using Python - Plain Text, Adding Attachments, HTML Emails, and More
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')


# -----------------------------------------------------------------------------
# 2. INSTANTIATING THE INFLUXDB CLIENT

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


def model_loading():
    # Loading all the ML models
    # (don't know why, but the joblib.load only works for the Linear Regression models...)
    for var in VARIABLES:
        if var in LIN_REG_VARS:
            globals()[f'model_{var}'] = joblib.load(f'modelsLSTM/{var}.h5')
        else:
            globals()[f'model_{var}'] = load_model(f'modelsLSTM/{var}.h5')
        # loading the scalers with joblib works just fine...
        globals()[f'scaler_{var}'] = joblib.load(f'my scalers/{var}.scale')

# %%
# ------------------------------------------------------------------------------
# 3. STARTING OUR EMAIL ASSISTANT OBJECT
email_assistant = Email_Intelligent_Assistant(EMAIL_ADDRESS=EMAIL_ADDRESS, EMAIL_PASSWORD=EMAIL_PASSWORD)


# -----------------------------------------------------------------------------
# 4. DEFINING THE PREDICTIONS FUNCTION

def predictions():

    for equip in EQUIPMENTS:
        
        # -----------------------------------------------------------------------------
        # Retrieving the necessary data to make a prediction (based on some of the settings)
        # influxDB documentation - https://docs.influxdata.com/influxdb/cloud/api-guide/client-libraries/python/
        # query to retrieve the data from the bucket relative to all the variables
        query = f'from(bucket:"{data_bucket}")\
            |> range(start: -1h)\
            |> sort(columns: ["_time"], desc: true)\
            |> limit(n: {PREVIOUS_STEPS})\
            |> filter(fn:(r) => r.DataType == "Real Data")\
            |> filter(fn:(r) => r.Equipment == "{equip}")'
        # don't know why I needed to subtract 2... but otherwise I would get more values than the ones I need....

        # Send the query defined above retrieving the needed data from the database
        result = query_api.query(org = INFLUXDB['Org'], query = query)

        # getting the values (it returns the values in the alphabetical order of the variables)
        results = []
        for table in result:
            for record in table.records:
                results.append((record.get_measurement(), record.get_value(), record.get_time()))

        # getting the variables of each equipment
        diff_variables = list()
        for i in range(len(results)):
            if results[i][0] not in diff_variables:
                diff_variables.append(results[i][0])
    

        # seperating each variable values - putting them in the dictionary "variable_vals"
        norm_variable_vals = dict()
        aux = list()
        for var in diff_variables:
            for i in range(len(results)):
                if results[i][0] == var:
                    aux.append(results[i][1])
            norm_variable_vals[f'{var}'] = globals()[f'scaler_{var}'].fit_transform(np.array(aux).reshape(-1, 1))
            aux = list()

        # now for the predictions
        for var in diff_variables:

            # reverse the vector so that the last measurement is the last timestamp
            values = np.flip(norm_variable_vals[f'{var}'])

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
            test_predict_y = globals()[f'scaler_{var}'].inverse_transform(np.array(test_predict_y).reshape(-1, 1))
        
            # getting the future timestamp
            actual_ts = results[0][2]
            future_ts = actual_ts + timedelta(seconds = INJECT_TIME_INTERVAL)

            # Sending the current prediction to a bucket 
            msg = influxdb_client.Point(var) \
                .tag("DataType", "Prediction Data") \
                .tag("Equipment", equip) \
                .field("value", float(test_predict_y)) \
                .time(future_ts, influxdb_client.WritePrecision.NS)
            write_api.write(bucket = data_bucket, org = INFLUXDB['Org'], record = msg)

            # Debugging the prediction
            print(f'{var} = {test_predict_y}')

        print('Predictions successfully sent to the database... Waiting 30 secs for the AD and next predictions \n')

# -----------------------------------------------------------------------------
# 5. DEFINING THE ANOMALY DETECTION FUNCTION

def anomaly_detection():

    for equip in EQUIPMENTS:
        # ------------------------------------------------------------------------------
        # RETRIEVING THE LAST 2 PREDICTED VALUES AND THE LAST REAL VALUE FOR EACH MEASUREMENT

        # Creating some empty auxiliary dictionaries
        error, predicted_vals, real_vals = dict(), dict(), dict()


        # query to retrieve the last 2 forecasted values for
        # why the range tahta way? because we can now retrieve the 2nd to last prediction, which will be related to the last REAL timestamp in the database
        query_pred = f'from(bucket:"{data_bucket}")\
            |> range(start: -1h)\
            |> last()\
            |> filter(fn:(r) => r.DataType == "Prediction Data")\
            |> filter(fn:(r) => r.Equipment == "{equip}")\
            |> filter(fn:(r) => r._field == "value")'

        # query to retrieve the last actual value
        query_last = f'from(bucket:"{data_bucket}")\
            |> range(start: -1h)\
            |> last()\
            |> filter(fn:(r) => r.DataType == "Real Data")\
            |> filter(fn:(r) => r.Equipment == "{equip}")\
            |> filter(fn:(r) => r._field == "value")'
        

        result_pred = query_api.query(org = INFLUXDB['Org'], query = query_pred)
        result_last = query_api.query(org = INFLUXDB['Org'], query = query_last)

        # getting the values for the forecasts and the real values
        results_pred = []
        results_last = []
        for table in result_pred:
            for record in table.records:
                results_pred.append((record.get_measurement(), record.get_value(), record.get_time()))
        for table in result_last:
            for record in table.records:
                results_last.append((record.get_measurement(), record.get_value(), record.get_time()))

        # getting the variables of each equipment
        diff_variables = list()
        for i in range(len(results_last)):
            if results_last[i][0] not in diff_variables:
                diff_variables.append(results_last[i][0])

        # Getting the timestamp of the values (to then put in the report)
        ts = list()
        for i in range(len(results_last)):
            ts.append(results_last[i][2].strftime("%m/%d/%Y, %H:%M:%S"))
            

        # normalizing the data received
        for i in range(len(results_pred)):
            # auxiliary variables
            var = results_pred[i][0]
            aux1 = results_pred[i][1]
            aux2 = results_last[i][1]
            # getting the non-normalized values of the variables
            predicted_vals[var] = globals()[f'scaler_{var}'].transform(np.float32(aux1).reshape(-1, 1))
            real_vals[var] = globals()[f'scaler_{var}'].transform(np.float32(aux2).reshape(-1, 1))
            # getting the error of the measurements
            aux_error = (np.abs(aux1 - aux2))/aux2
            error[var] = aux_error
            
        print(error)
            
        # -----------------------------------------------------------------------------------------------------------
        # COMPARING THE TWO RESULTS IN ORDER TO DETECT AN ANOMALY
        # for this I'll create a pandas DataFrame with some important columns, which can then be more easily used to send the reports, etc

        # sorting the variables alphabetically, as the values come from the database in the alphabetical order of the variables' names
        variables = list(diff_variables)
        variables.sort()

        df = pd.DataFrame(index = diff_variables)
        df[['Timestamp', 'Predicted Value', 'Real Value', 'Error']] = [ts, predicted_vals.values(), real_vals.values(), error.values()]

        # setting up an anomaly filter
        anomaly_filter = (df['Error'] > AD_THRESHOLD)
        # getting the anomalies
        anomaly_df = df.loc[anomaly_filter]

        for i in range(len(error)):
            var = variables[i]
            # Sending the Error values to the database
            msg = influxdb_client.Point(var) \
                .tag("DataType", "Error") \
                .tag("Equipment", equip) \
                .field("value", error[var]) \
                .time(results_last[0][2], influxdb_client.WritePrecision.NS)
            write_api.write(bucket = data_bucket, org = INFLUXDB['Org'], record = msg)

        # adding the anomalies to the report
        email_assistant.add_anomalies(anomaly_dataframe = anomaly_df)

        print('The add_anomalies function is working... \n')

# -------------------------------------------------------------------------------------------------
# 6. SCHEDULLING SOME FUNCTIONS TO BE EXECUTED
# for demonstration purposes, uncomment the minutes ones
# schedule.every(5).minutes.do(email_assistant.send_email_notification)
# schedule.every(5).minutes.do(email_assistant.save_report)
# schedule.every(5).minutes.do(email_assistant.generate_blank_excel)
schedule.every(10).minutes.do(model_loading)
# schedule.every().hour.do(email_assistant.send_email_notification)
schedule.every().hour.do(email_assistant.save_report)
schedule.every().hour.do(email_assistant.generate_blank_excel)
schedule.every(INJECT_TIME_INTERVAL).seconds.do(predictions)
schedule.every(INJECT_TIME_INTERVAL).seconds.do(anomaly_detection)


# generating the first blank excel before the infinite cycle
email_assistant.generate_blank_excel()

# initial load of the models
model_loading()
# making a first batch of predictions - just to guarantee that the anomaly detection program has indeed predicted data to work with
predictions()


# ---------------------------------------------------------------------------------
# 7. INFINITE CYCLE

while True:

    schedule.run_pending()

    # predictions()
    # time.sleep(INJECT_TIME_INTERVAL)
    # anomaly_detection()

