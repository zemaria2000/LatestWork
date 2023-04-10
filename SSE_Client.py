# For more useful information about the SSEClient library, check the links below:
# https://pypi.org/project/sseclient-py/
# https://pypi.org/project/sseclient/

# For more useful information about the InfluxDB library, check the links below:
# https://docs.influxdata.com/influxdb/cloud/api-guide/client-libraries/python/
# https://pypi.org/project/influxdb/


from sseclient import SSEClient
import json, yaml
import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime
from settings import SSE, INFLUXDB


# ---------------------- loading some variables -------------------------- #
# with open('config.yaml') as file:
#     Config = yaml.full_load(file)

# sse_host, sse_user, sse_pass = Config['SSE']['URL'], Config['SSE']['Auth']['User'], Config['SSE']['Auth']['Pass']
# db_token, db_url, db_bucket, db_org = Config['Database']['Token'], Config['Database']['URL'], Config['Database']['Bucket'], Config['Database']['Org']

sse_host, sse_user, sse_pass = SSE['URL'], SSE['Auth']['User'], SSE['Auth']['Pass']
db_token, db_url, db_bucket, db_org = INFLUXDB['Token'], INFLUXDB['URL'], INFLUXDB['Bucket'], INFLUXDB['Org']


# ------------------- INITIALIZING THE SSE AND INFLUXDB CLIENTS ----------------- #

# generate the SSE Client
messages = SSEClient(sse_host, auth = (sse_user, sse_pass))

# Instantiate the InfluxDB client
client = influxdb_client.InfluxDBClient(
    url=db_url,
    token=db_token,
    org=db_org
)
write_api = client.write_api(write_options=SYNCHRONOUS)


# -------------------- FUNCTION THAT SENDS DATA TO INFLUXDB ---------------------- #

def send_values(measurement, equipment, value):
    to_send = influxdb_client.Point(measurement) \
        .tag("Equipment", equipment) \
        .tag("DataType", "Real Data") \
        .field("value", value) \
        .time(datetime.utcnow(), influxdb_client.WritePrecision.NS)

    return write_api.write(bucket = db_bucket, org = db_org, record = to_send)


# ------------------------ RECEIVING MESSAGES FROM DITTO ------------------------- #

for msg in messages:
    
    try:

        msg_decoded = json.loads(str(msg))
        tenant, device = msg_decoded["thingId"].split(':')[0], msg_decoded["thingId"].split(':')[1]
        
        print('New Data:')
        
        for key in msg_decoded["features"]:
            
            # Get the values of the properties
            val = msg_decoded["features"][key]["properties"]["value"]

            # Send the respective query to InfluxDB
            send_values(measurement = key, equipment = device, value = val)

            # Just to know which tenant and device is being updated
            print(f"Tenant: {tenant}", f"Device: {device}", f"{key} : {val}", sep='  ')

        print("")

    except:
        print("Incomplete or unsuccessful reading: ", msg, '\n')

