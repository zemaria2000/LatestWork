
import pandas as pd
from datetime import datetime
import smtplib
from email.message import EmailMessage
from settings import EXCEL_DIR, VARIABLES, INFLUXDB, INJECT_TIME_INTERVAL
import influxdb_client
from influxdb_client.client.write_api import ASYNCHRONOUS
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import time
import requests
import json


class Email_Intelligent_Assistant:

    def __init__(self, EMAIL_ADDRESS, EMAIL_PASSWORD, url, token, org, bucket):
        self.EMAIL_ADDRESS = EMAIL_ADDRESS
        self.EMAIL_PASSWORD = EMAIL_PASSWORD
        self.url = url
        self.org = org
        self.token = token
        self.bucket = bucket
        self.client = influxdb_client.InfluxDBClient(
                            url = url,
                            token = token,
                            org = org
                        )

    # Generating a new blank excel
    def generate_blank_excel(self):
        cols = {'Timestamp': [], 'Predicted Value': [], 'Real Value': [], 'Norm Difference': [], 'Thresholds': [], 'Severity': [], 'Notes': []}
        new_file = pd.DataFrame(cols)
        new_file.to_excel('Current_Report.xlsx')



    # inputting new anomalies into the report
    def add_anomalies(self, anomaly_dataframe: pd.DataFrame):
        
        # "Original File" 
        file1 = pd.read_excel('Current_Report.xlsx', index_col = 'Unnamed: 0')
        
        if len(anomaly_dataframe) > 0:

            notes, severity = [], []
            for var in anomaly_dataframe.index:
                
                # Column with the severity of the anomalies
                if (anomaly_dataframe.loc[var, 'Norm Difference'] >=  anomaly_dataframe.loc[var, 'Thresholds']) and (anomaly_dataframe.loc[var, 'Norm Difference'] < 5 * anomaly_dataframe.loc[var, 'Thresholds']):
                    severity.append('Light')
                elif (anomaly_dataframe.loc[var, 'Norm Difference'] >= 5 * anomaly_dataframe.loc[var, 'Thresholds']) and (anomaly_dataframe.loc[var, 'Norm Difference'] < 10 * anomaly_dataframe.loc[var, 'Thresholds']):
                    severity.append('Medium')
                elif (anomaly_dataframe.loc[var, 'Norm Difference'] >= 10 * anomaly_dataframe.loc[var, 'Thresholds']):
                    severity.append('Severe')          


                # Creating a column with notes about the data
                if anomaly_dataframe.loc[var]['Predicted Value'] > anomaly_dataframe.loc[var]['Real Value']:
                    notes.append('The real value was far to low than the prediction given')
                else:
                    notes.append('The real value was to high when compared with the prediction given')

            anomaly_dataframe.loc[:, 'Severity'] = severity
            anomaly_dataframe.loc[:, 'Notes'] = notes

            # Adding the new data
            new_file = pd.concat([file1, anomaly_dataframe], ignore_index=False)
        
        else:
            new_file = file1
        # Saving the new excel file

        new_file.to_excel('Current_Report.xlsx')



    # Saving the hourly report
    def save_report(self):

        ts = datetime.now().strftime("%Y-%m-%d__%H-%M")
        report = pd.read_excel('Current_Report.xlsx')
        report.to_excel(f'{EXCEL_DIR}{str(ts)}.xlsx')

        print(f"Report succesffully saved at {EXCEL_DIR} directory, with the name '{str(ts)}.xlsx'! \n\n")



    # Plotting some graphs to send as well via email
    def graph_plotting(self):

        st = time.time()    
        query_api = self.client.query_api()
        data_bucket = self.bucket

        query = f'from(bucket:"{data_bucket}")\
            |> range(start: -1h)\
            |> filter(fn:(r) => r.DataType == "Prediction Data" or r.DataType == "Real Data")\
            |> filter(fn:(r) => r._field == "value")'
        
        result = query_api.query(org = self.org, query = query)

        # real_data, pred_data, real_ts, pred_ts = dict(), dict(), dict(), dict()

        for var in VARIABLES:
            # getting the values
            real_vals, predicted_vals, real_ts_vals, pred_ts_vals = [], [], [], []
            for table in result:
                for record in table.records:
                    if var == record.get_measurement():
                        if record.values.get("DataType") == "Prediction Data": 
                            predicted_vals.append(record.get_value())
                            pred_ts_vals.append(record.get_time())
                        else:
                            real_vals.append(record.get_value())
                            real_ts_vals.append(record.get_time())
            # # putting them in the dictionaries
            # real_data[var] = real_vals
            # pred_data[var] = predicted_vals
            # real_ts[var] = real_ts_vals
            # pred_ts[var] = pred_ts_vals


            if len(real_vals) > 0:
                
                plt.style.use('ggplot')
                plt.plot(real_ts_vals, real_vals, '-r', linewidth = 0.5)
                plt.plot(pred_ts_vals, predicted_vals, '-b', linewidth = 0.5)
                plt.legend(['Real Values', 'Predicted Values'])
                plt.title(f"Real vs Predictions values for {var}")

                plt.savefig(f'Graphs/{var}.png')

                plt.close()

        et = time.time()

        elapsed_time = et - st

        print('\n\n\n\n\n---------------------------------------------------------------------')
        print('Execution time for the anomaly graph plotting:', elapsed_time, 'seconds')
        print('---------------------------------------------------------------------')


    # Generating the email message to be sent
    def send_email_notification(self):
            
        # Loading the excel file
        df = pd.read_excel('Current_Report.xlsx', index_col = 'Unnamed: 0')
        
        # If there were anomalies..
        if len(df) > 0:
            df.set_index('Variable')

            # some data processing...
            # number of anomaly occurrences per variable
            anomaly_occur = df.groupby(df['Variable']).size()
            number_anomalies = df.shape[0]
            high_anomalies = len(df[df['Notes'] == 'The real value was far to low than the prediction given'])
            low_anomalies = len(df[df['Notes'] == 'The real value was to high when compared with the prediction given'])
            light_anomalies = len(df[df['Severity'] == 'Light'])
            medium_anomalies = len(df[df['Severity'] == 'Medium'])
            severe_anomalies = len(df[df['Severity'] == 'Severe'])
  
            # message to send
            msg_to_send = f"In total there were {number_anomalies} anomalous points, with {severe_anomalies} severe ones, detected during the last hour \n{high_anomalies} were values that were far too big when compared to the predictions and {low_anomalies} were values too low compared to the predictions \n\n In terms of the variables that had anomalies, we had: \n"

            for var in VARIABLES:
                if var in anomaly_occur:
                    msg_to_send += f'   - {var} with {anomaly_occur[var]} anomalies;\n'
            
            msg_to_send += f"\n In terms of the severity of the anomalies, there were: \n"
            msg_to_send += f"   - {light_anomalies} light anomalies (with relatively small errors); \n"
            msg_to_send += f"   - {medium_anomalies} medium anomalies (with bigger prediction errors); \n"
            msg_to_send += f"   - {severe_anomalies} severe anomalies (significant predictions errors). \n\n"
            
            msg_to_send += '\n\n Attached to this email we have an Excel file with all the anomalies, their respective timestamps and some more useful information, as well as the graphs with the behaviour of each variable'
        
        
        else:
            msg_to_send = f"There were no anomalies detected during the last hour!"


        # Instantiating the EmailMessage object
        msg = EmailMessage()

        # mail sender and receiver
        msg['From'] = self.EMAIL_ADDRESS
        # msg['To'] = 'zemaria-sta@hotmail.com'

        # Sending emails to several contacts
        # contacts = ['zemaria-sta@hotmail.com', 'josemaria@ua.pt']
        # msg['To'] = ', '.join(contacts)

        msg['To'] = ['josemaria@ua.pt']

        # Subject and content of the message
        msg['Subject'] = 'Hourly report'
        msg.set_content(msg_to_send)
        # Opening the excel report...
        with open('Current_Report.xlsx', 'rb') as file:
            file_data = file.read()
            file_name = "HourlyReport.xlsx"

        if len(df) > 0:
            # Adding the excel file as an attachment to the email
            msg.add_attachment(file_data, maintype = 'application', subtype = 'xlsx', filename = file_name)

        # for var in VARIABLES:
            
        #     with open(f'Graphs/{var}.png', 'rb') as image:

        #         image_data = image.read()
        #         image_name = f'{var} Real vs Pred'
        #         msg.add_attachment(image_data, maintype = 'image', subtype = 'png', filename = image_name)


        # sending the email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            # login to our email server
            smtp.login(self.EMAIL_ADDRESS, self.EMAIL_PASSWORD)       # Password that is given by google when enabling 2 way authentication 
            # sending the message
            smtp.send_message(msg)
            print(f"\n \n Email with the last shift's report has been sent \n \n")



    def send_telegram_notification(self):

        # Telegram Bot variables
        API_Token = '6121421687:AAEZq-HQmCe9aW39dr_mHoK9e9csYMCgcF4'
        GroupID = '-890547248' 

        # Loading the excel
        document = open('Current_report.xlsx', 'rb')

        # Defining the message to send
        msg = f"The email with the latest report has been sent. Here is the report of last hour's events"

        try:
            URL = 'https://api.telegram.org/bot' + API_Token + '/sendDocument?chat_id=' + GroupID
            requests.post(url = URL, files = {'document': document}, data = {'caption': msg})

        except Exception as e:
            msg = str(e) + ": Exception occurred in SendMessageToTelegram"
            print(msg)    # Processing the info
