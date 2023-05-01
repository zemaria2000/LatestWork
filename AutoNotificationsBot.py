#%%
import influxdb_client
from influxdb_client.client.write_api import ASYNCHRONOUS
from settings import VARIABLES, INFLUXDB, MULTIPLIER, INJECT_TIME_INTERVAL
import telepot
import numpy as np
import time
import requests
import pandas as pd
import joblib
import schedule

# Define the bot's credentials (and the group credential as well)
API_Token = '6121421687:AAEZq-HQmCe9aW39dr_mHoK9e9csYMCgcF4'
GroupID = '-890547248' 


# Connect to the InfluxDB database
client = influxdb_client.InfluxDBClient(
    url = INFLUXDB['URL'],
    token = INFLUXDB['Token'],
    org = INFLUXDB['Org']
)

# Instantiate the write api client
write_api = client.write_api(write_options = ASYNCHRONOUS)
# Instantiate the query api client
query_api = client.query_api()

data_bucket = INFLUXDB['Bucket']

# Getting the thresholds for anomaly detection
thresholds = dict()
# Getting all the values of the RMSEs
for var in VARIABLES:
    thresholds[var] = (np.load(f'Models/{var}.npy',allow_pickle='TRUE').item()['val_root_mean_squared_error'])*MULTIPLIER[var]
    # loading the scalers
    globals()[f'scaler_{var}'] = joblib.load(f'Scalers/{var}.scale')

# Oredering them alphabetically
thresholds = dict(sorted(thresholds.items()))


# Define the function to handle incoming messages
def check_anomalies(thresholds):
    
    # Generate an empty DataFrame to put the anomalies in
    anomaly_df = pd.DataFrame(columns = ['Variable', 'Difference', 'Threshold'])

    to_store = []
    for var in VARIABLES:
        
        # Auxiliary dictionary
        aux = dict()

        # Retrieve data from the InfluxDB bucket
        query_pred = f'from(bucket:"{data_bucket}")\
            |> range(start: -5s)\
            |> last()\
            |> filter(fn:(r) => r._measurement == "{var}")\
            |> filter(fn:(r) => r.DataType == "Prediction Data")\
            |> filter(fn:(r) => r._field == "value")'

        # query to retrieve the last actual value
        query_last = f'from(bucket:"{data_bucket}")\
            |> range(start: -5s)\
            |> last()\
            |> filter(fn:(r) => r._measurement == "{var}")\
            |> filter(fn:(r) => r.DataType == "Real Data")\
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
       
        # In case there are predictions made, as well as real data 
        if len(results_last) > 0 and len(results_pred) > 0:
            # Normalizing the prediction and the real value
            prediction = globals()[f'scaler_{var}'].transform(np.array([[results_pred[0][1]]]))
            real = globals()[f'scaler_{var}'].transform(np.array([[results_last[0][1]]]))
            # getting the difference of the measurements to then use the rmse to determine what's an anomaly
            difference = round(np.abs(float(prediction) - float(real)), 5)
            threshold = thresholds[var]

            print(f'Var: {var}, Prediction: {prediction}, Real Value: {real}, Difference: {difference} \n')

            # Calculate the difference and send a notification if it exceeds the threshold
            if difference > threshold:
                aux = {'Variable': var, 'Difference': difference, 'Threshold': threshold}
                to_store.append(aux)          

        else: 
            print(f"There's no available pair of real data and prediction data for variable {var}!")

    anomaly_df = pd.DataFrame(to_store)
    print(anomaly_df)
    
    return anomaly_df


# Function that allows me to send messages with the bot
def SendMessageToTelegram(anomaly_df: pd.DataFrame):

    msg = ""

    if len(anomaly_df) == 0:

        print("No anomalies")
    
    else:

        if len(anomaly_df) == 1:

            msg += "There's been an anomaly in the last pair of predictions + real data: \n" 
        else:
            msg += f"There's been some anomalies in the last pair of predictions + real data: \n"
    
        for var in anomaly_df.loc[:, 'Variable']:

            line = anomaly_df.loc[anomaly_df['Variable'] == var]
            diff = line['Difference']
            thresh = line['Threshold']

            msg += f"   - Variable {var} had a difference of {round(float(diff), 5)} when it's threshold was only {round(float(thresh), 5)} \n"

        print(msg)

        try:
            URL = 'https://api.telegram.org/bot' + API_Token + '/sendMessage?chat_id=' + GroupID

            textdata = {"text": msg}
            response = requests.request("POST", url = URL, params = textdata)

            print(response)

        except Exception as e:

            msg = str(e) + ": Exception occurred in SendMessageToTelegram"
            print(msg)    # Processing the info
        

# Function that runs all the necessary ones
def scheduled_job():

    df = check_anomalies(thresholds)

    SendMessageToTelegram(df)


# schedulling the functions to be ran every 2 seconds
df = schedule.every(INJECT_TIME_INTERVAL).seconds.do(scheduled_job)


while True:

    schedule.run_pending()

    time.sleep(1)







# # Set up the webhook URL for the bot
# webhook_url = 'https://api.telegram.org/bot6121421687:AAEZq-HQmCe9aW39dr_mHoK9e9csYMCgcF4'
# telepot.Bot.setWebhook(webhook_url)

# # Create the bot with the API token
# bot = telepot.Bot('6121421687:AAEZq-HQmCe9aW39dr_mHoK9e9csYMCgcF4')

# # Start the message loop
# bot.message_loop(handle_message)

# # Keep the program running
# while True:
#     pass
# %%
